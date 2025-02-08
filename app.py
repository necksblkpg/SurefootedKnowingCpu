from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import firebase_admin
from firebase_admin import credentials, auth, storage, firestore
import os
from datetime import timedelta, datetime
import pytz  # Ny import

app = Flask(__name__)
app.secret_key = 'super-hemligt-nyckel'  # OBS: Byt ut mot en stark hemlighet i produktion

def get_safe_login_name():
    """Hämtar och sanerar användarens inloggningsnamn (e-post) från sessionen."""
    user = session.get('user')
    if not user:
        return 'unknown'
    login_name = user.get('email', 'unknown')
    return login_name.replace('@', '_').replace('.', '_')

# Hjälpfunktion för att konvertera UTC-tid till lokal tid (Europe/Stockholm)
def convert_to_local(dt):
    if dt is None:
        return None
    # Om dt är "naivt" (saknar tzinfo), anta att det är UTC
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_tz = pytz.timezone("Europe/Stockholm")
    return dt.astimezone(local_tz)

# Lägg till denna hjälpfunktion för att konvertera strängar till datetime
def parse_date(date_string):
    if not date_string:
        return None
    try:
        # Konvertera till datetime och sätt tiden till midnatt
        date = datetime.strptime(date_string, '%Y-%m-%d')
        return datetime.combine(date.date(), datetime.min.time())
    except ValueError:
        return None

# Hämta värdena från Replit Secrets (använd exakt samma nyckelnamn som du har satt)
firebase_api_key = os.environ.get("apiKey")
firebase_auth_domain = os.environ.get("authDomain")
firebase_project_id = os.environ.get("projectId")
firebase_storage_bucket = os.environ.get("storageBucket")
firebase_messaging_sender_id = os.environ.get("messagingSenderId")
firebase_app_id = os.environ.get("appId")

if not firebase_storage_bucket:
    raise ValueError("Miljövariabeln 'storageBucket' är inte satt. Sätt den i Replit Secrets!")

# Initiera Firebase Admin SDK med servicekonto
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': firebase_storage_bucket  # T.ex. "template-d8a76.firebasestorage.app"
})
bucket = storage.bucket()

# Initiera Firestore-klienten
db = firestore.client()

# Konstruera Firebase-konfigurationen som ett dictionary (för klienten)
firebase_config = {
    "apiKey": firebase_api_key,
    "authDomain": firebase_auth_domain,
    "projectId": firebase_project_id,
    "storageBucket": firebase_storage_bucket,
    "messagingSenderId": firebase_messaging_sender_id,
    "appId": firebase_app_id
}

@app.route('/')
def index():
    return render_template("index.html", firebase_config=firebase_config)

@app.route('/login', methods=['POST'])
def login():
    id_token = request.form.get("idToken")
    if id_token:
        try:
            decoded_token = auth.verify_id_token(id_token)
            session['user'] = decoded_token
            print(f"Användare inloggad: {decoded_token.get('email')} (UID: {decoded_token.get('uid')})")
            return redirect(url_for('todos'))
        except Exception as e:
            print("Token-verifiering misslyckades:", e)
            return "Ogiltig token", 400
    return "Token saknas", 400

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('index'))

    safe_login_name = get_safe_login_name()

    # Lista filer i mappen "csv_uploads/<safe_login_name>/"
    blobs = bucket.list_blobs(prefix=f"csv_uploads/{safe_login_name}/")
    files = []
    for blob in blobs:
        url = blob.generate_signed_url(expiration=timedelta(minutes=15))
        filename = blob.name.split("/")[-1]
        files.append({'name': filename, 'url': url})

    # Hämta metadata från Firestore
    metadata_docs = db.collection("users").document(safe_login_name).collection("csv_files").stream()
    metadata_map = {}
    for doc in metadata_docs:
        metadata_map[doc.id] = doc.to_dict()

    # Kombinera metadata med filinformationen och konvertera tiderna
    for file in files:
        meta = metadata_map.get(file['name'], {})
        file['description'] = meta.get('description', '')
        file['tags'] = meta.get('tags', '')
        if meta.get('upload_time'):
            file['upload_time'] = convert_to_local(meta.get('upload_time')).strftime('%Y-%m-%d %H:%M:%S')
        else:
            file['upload_time'] = ''
        if meta.get('last_edited'):
            file['last_edited'] = convert_to_local(meta.get('last_edited')).strftime('%Y-%m-%d %H:%M:%S')
        else:
            file['last_edited'] = ''

    # Hämta uppgifter för det aktuella projektet
    todos = db.collection("users").document(safe_login_name).collection("todos").where("project_id", "==", currentProject).stream()

    return render_template("dashboard.html", user=session['user'], files=files, todos=todos)

@app.route('/upload', methods=['GET', 'POST'])
def upload_route():
    if 'user' not in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        if 'file' not in request.files:
            return "Ingen fil skickades", 400
        file = request.files['file']
        if file.filename == '':
            return "Ingen fil vald", 400
            
        # Kontrollera filtyp
        allowed_extensions = {'.csv', '.pdf'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            return "Ogiltigt filformat. Endast CSV och PDF är tillåtna.", 400
            
        safe_login_name = get_safe_login_name()
        # Spara filen i mappen: uploads/<safe_login_name>/<filnamn>
        blob_path = f'uploads/{safe_login_name}/{file.filename}'
        blob = bucket.blob(blob_path)
        blob.upload_from_file(file)

        # Spara metadata i Firestore
        metadata = {
            'filename': file.filename,
            'blob_path': blob_path,
            'file_type': file_ext[1:],  # Spara filtyp utan punkt
            'upload_time': firestore.SERVER_TIMESTAMP,
            'last_edited': firestore.SERVER_TIMESTAMP,
            'user_email': session['user'].get('email'),
            'description': '',
            'tags': ''
        }
        db.collection("users").document(safe_login_name).collection("files").document(file.filename).set(metadata)

        return f"Filen laddades upp och sparades i mappen {safe_login_name}!"
    return render_template("upload.html")

@app.route('/delete_file', methods=['POST'])
def delete_file():
    if 'user' not in session:
        return redirect(url_for('index'))
    safe_login_name = get_safe_login_name()
    filename = request.form.get("filename")
    if not filename:
        return "Filen saknas", 400
    blob_path = f"csv_uploads/{safe_login_name}/{filename}"
    blob = bucket.blob(blob_path)
    blob.delete()
    # Ta bort metadata i Firestore
    db.collection("users").document(safe_login_name).collection("csv_files").document(filename).delete()
    return redirect(url_for('dashboard'))

@app.route('/rename_file', methods=['POST'])
def rename_file():
    if 'user' not in session:
        return redirect(url_for('index'))
    safe_login_name = get_safe_login_name()
    old_filename = request.form.get("old_filename")
    new_filename = request.form.get("new_filename")
    if not old_filename or not new_filename:
        return "Filnamn saknas", 400
    if "/" in new_filename or "\\" in new_filename:
        return "Felaktigt filnamn - mappändring ej tillåten", 400
        
    # Kontrollera filtyp
    allowed_extensions = {'.csv', '.pdf'}
    file_ext = os.path.splitext(new_filename)[1].lower()
    if file_ext not in allowed_extensions:
        return "Ogiltigt filformat. Endast CSV och PDF är tillåtna.", 400
        
    old_blob_path = f"uploads/{safe_login_name}/{old_filename}"
    new_blob_path = f"uploads/{safe_login_name}/{new_filename}"
    
    old_blob = bucket.blob(old_blob_path)
    bucket.copy_blob(old_blob, bucket, new_blob_path)
    old_blob.delete()
    # Uppdatera metadata i Firestore
    doc_ref = db.collection("users").document(safe_login_name).collection("csv_files").document(old_filename)
    metadata = doc_ref.get().to_dict()
    if metadata:
        metadata['filename'] = new_filename
        metadata['blob_path'] = new_blob_path
        metadata['last_edited'] = firestore.SERVER_TIMESTAMP
        db.collection("users").document(safe_login_name).collection("csv_files").document(new_filename).set(metadata)
        doc_ref.delete()
    return redirect(url_for('dashboard'))

@app.route('/update_metadata', methods=['POST'])
def update_metadata():
    if 'user' not in session:
        return redirect(url_for('index'))
    safe_login_name = get_safe_login_name()
    filename = request.form.get("filename")
    description = request.form.get("description")
    tags = request.form.get("tags")
    if not filename:
        return "Filen saknas", 400
    doc_ref = db.collection("users").document(safe_login_name).collection("csv_files").document(filename)
    doc_ref.set({
        "description": description,
        "tags": tags,
        "last_edited": firestore.SERVER_TIMESTAMP
    }, merge=True)
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/projects')
def get_projects():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    safe_login_name = get_safe_login_name()
    projects_ref = db.collection("users").document(safe_login_name).collection("projects")
    projects = []
    
    for doc in projects_ref.stream():
        project = doc.to_dict()
        project['id'] = doc.id
        projects.append(project)
    
    return jsonify(projects)

@app.route('/add_project', methods=['POST'])
def add_project():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    safe_login_name = get_safe_login_name()
    name = request.form.get('name')
    color = request.form.get('color', '#808080')  # Default grå färg
    
    if not name:
        return jsonify({'error': 'Project name is required'}), 400
    
    project_data = {
        'name': name,
        'color': color,
        'created_at': datetime.now(),
        'updated_at': datetime.now()
    }
    
    project_ref = db.collection("users").document(safe_login_name).collection("projects").document()
    project_ref.set(project_data)
    
    project_data['id'] = project_ref.id
    return jsonify(project_data)

@app.route('/todos')
def todos():
    if 'user' not in session:
        return redirect(url_for('index'))
    
    safe_login_name = get_safe_login_name()
    
    # Hämta alla projekt först
    projects_ref = db.collection("users").document(safe_login_name).collection("projects")
    projects = []
    for doc in projects_ref.stream():
        project = doc.to_dict()
        project['id'] = doc.id
        projects.append(project)
    
    # Om inga projekt finns, skapa ett standardprojekt "Inkorg"
    if not projects:
        inbox_project = {
            'name': 'Inkorg',
            'color': '#808080',
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        inbox_ref = projects_ref.document()
        inbox_ref.set(inbox_project)
        inbox_project['id'] = inbox_ref.id
        projects.append(inbox_project)
    
    # Hämta alla todos och gruppera dem efter projekt
    todos_ref = db.collection("users").document(safe_login_name).collection("todos")
    todos = []
    for doc in todos_ref.stream():
        todo = doc.to_dict()
        todo['id'] = doc.id
        
        # Konvertera deadline till rätt format om den finns
        if todo.get('deadline'):
            if isinstance(todo['deadline'], datetime):
                todo['deadline'] = todo['deadline'].strftime('%Y-%m-%d')
            elif isinstance(todo['deadline'], str):
                try:
                    date = datetime.strptime(todo['deadline'], '%Y-%m-%d')
                    todo['deadline'] = date.strftime('%Y-%m-%d')
                except ValueError:
                    todo['deadline'] = None
        
        todos.append(todo)
    
    return render_template('todos.html', todos=todos, projects=projects)

@app.route('/add_todo', methods=['GET', 'POST'])
def add_todo():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    safe_login_name = get_safe_login_name()
    
    title = request.form.get('title')
    description = request.form.get('description', '')
    deadline = parse_date(request.form.get('deadline'))
    priority = int(request.form.get('priority', 4))
    project_id = request.form.get('project_id')  # Hämta projekt-ID
    
    # Skapa todo-dokumentet
    todo_data = {
        'title': title,
        'description': description,
        'deadline': deadline,
        'priority': priority,
        'project_id': project_id,  # Spara projekt-ID
        'status': 'not_started',
        'created_at': datetime.now(),
        'updated_at': datetime.now(),
        'files': []
    }
    
    # Lägg till i Firestore
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document()
    todo_ref.set(todo_data)
    
    # Hantera filuppladdning om en fil finns
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            try:
                # Spara filen och uppdatera todo med filinformation
                blob_path = f'todo_files/{safe_login_name}/{todo_ref.id}/{file.filename}'
                blob = bucket.blob(blob_path)
                
                # Spara original filnamn och content type
                content_type = file.content_type or 'application/octet-stream'
                metadata = {
                    'original_filename': file.filename,
                    'content_type': content_type
                }
                blob.metadata = metadata
                
                # Få filstorlek
                file.seek(0, 2)  # Gå till slutet av filen
                file_size = file.tell()  # Få position (storlek)
                file.seek(0)  # Återgå till början
                
                # Ladda upp filen
                blob.upload_from_file(file, content_type=content_type)
                
                # Skapa signerad URL för nedladdning
                url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(minutes=15),
                    method="GET"
                )
                
                # Uppdatera todo med filinformation
                file_data = {
                    'filename': file.filename,
                    'blob_path': blob_path,
                    'size': file_size,
                    'content_type': content_type,
                    'upload_time': datetime.now(),
                    'download_url': url
                }
                
                todo_ref.update({
                    'files': firestore.ArrayUnion([file_data]),
                    'updated_at': datetime.now()
                })
                
            except Exception as e:
                print(f"Fel vid filuppladdning: {e}")
                # Fortsätt även om filuppladdningen misslyckas
    
    # Hämta den skapade todo:n för att returnera
    todo = todo_ref.get().to_dict()
    todo['id'] = todo_ref.id
    
    return jsonify(todo)

@app.route('/update_todo_status/<todo_id>', methods=['POST'])
def update_todo_status(todo_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    new_status = data.get('status')
    
    if not new_status:
        return jsonify({'error': 'Missing status'}), 400
    
    safe_login_name = get_safe_login_name()
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
    
    todo_ref.update({
        'status': new_status,
        'updated_at': datetime.now()
    })
    
    return jsonify({'success': True})

@app.route('/upload_todo_file/<todo_id>', methods=['POST'])
def upload_todo_file(todo_id):
    if 'user' not in session:
        return redirect(url_for('index'))
    
    if 'file' not in request.files:
        return "Ingen fil skickades", 400
    
    file = request.files['file']
    if file.filename == '':
        return "Ingen fil vald", 400
        
    # Kontrollera filtyp
    allowed_extensions = {'.csv', '.pdf'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return "Ogiltigt filformat. Endast CSV och PDF är tillåtna.", 400
        
    safe_login_name = get_safe_login_name()
    
    try:
        # Spara filen i en specifik mapp för todo-filer
        blob_path = f'todo_files/{safe_login_name}/{todo_id}/{file.filename}'
        blob = bucket.blob(blob_path)
        
        # Spara original filnamn och content type
        content_type = 'application/pdf' if file_ext == '.pdf' else 'text/csv'
        metadata = {
            'original_filename': file.filename,
            'content_type': content_type
        }
        blob.metadata = metadata
        
        # Ladda upp filen och få filstorlek
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        blob.upload_from_file(file, content_type=content_type)
        
        # Skapa signerad URL för nedladdning
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="GET"
        )

        # Uppdatera todo-dokumentet med filinformation
        todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
        
        current_time = datetime.now()
        file_data = {
            'filename': file.filename,
            'blob_path': blob_path,
            'size': file_size,
            'content_type': content_type,
            'upload_time': current_time,
            'download_url': url
        }
        
        # Uppdatera todo-dokumentet
        todo_ref.update({
            'files': firestore.ArrayUnion([file_data]),
            'updated_at': current_time
        })
        
        return redirect(url_for('todos'))
        
    except Exception as e:
        print(f"Fel vid filuppladdning: {e}")
        return "Ett fel uppstod vid filuppladdning", 500

@app.route('/download_todo_file/<todo_id>/<filename>')
def download_todo_file(todo_id, filename):
    if 'user' not in session:
        return redirect(url_for('index'))
    
    safe_login_name = get_safe_login_name()
    blob_path = f'todo_files/{safe_login_name}/{todo_id}/{filename}'
    
    try:
        blob = bucket.blob(blob_path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="GET"
        )
        return redirect(url)
    except Exception as e:
        print(f"Fel vid generering av nedladdningslänk: {e}")
        return "Kunde inte generera nedladdningslänk", 500

@app.route('/delete_todo_file/<todo_id>/<filename>', methods=['POST'])
def delete_todo_file(todo_id, filename):
    if 'user' not in session:
        return redirect(url_for('index'))
    
    safe_login_name = get_safe_login_name()
    
    # Ta bort filen från Storage
    blob_path = f'todo_files/{safe_login_name}/{todo_id}/{filename}'
    blob = bucket.blob(blob_path)
    blob.delete()
    
    # Uppdatera todo-dokumentet
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
    todo_doc = todo_ref.get()
    
    if todo_doc.exists:
        todo_data = todo_doc.to_dict()
        files = todo_data.get('files', [])
        # Ta bort filen från files-arrayen
        files = [f for f in files if f['filename'] != filename]
        
        todo_ref.update({
            'files': files,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
    
    return redirect(url_for('todos'))

@app.route('/delete_todo/<todo_id>', methods=['POST'])
def delete_todo(todo_id):
    if 'user' not in session:
        return redirect(url_for('index'))
    
    safe_login_name = get_safe_login_name()
    
    # Ta först bort alla tillhörande filer
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
    todo_doc = todo_ref.get()
    
    if todo_doc.exists:
        todo_data = todo_doc.to_dict()
        files = todo_data.get('files', [])
        
        # Ta bort filer från Storage
        for file in files:
            blob = bucket.blob(file['blob_path'])
            blob.delete()
    
    # Ta bort todo-dokumentet
    todo_ref.delete()
    
    return redirect(url_for('todos'))

@app.route('/edit_todo/<todo_id>', methods=['POST'])
def edit_todo(todo_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    safe_login_name = get_safe_login_name()
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
    
    try:
        # Hämta formulärdata
        title = request.form.get('title')
        description = request.form.get('description')
        deadline = request.form.get('deadline')
        priority = int(request.form.get('priority', 4))
        project_id = request.form.get('project_id')
        
        # Skapa uppdateringsdata
        update_data = {
            'title': title,
            'description': description,
            'priority': priority,
            'project_id': project_id,
            'updated_at': datetime.now()
        }
        
        if deadline:
            update_data['deadline'] = parse_date(deadline)
        
        # Uppdatera todo
        todo_ref.update(update_data)
        
        # Hantera ny fil om en sådan laddades upp
        if 'file' in request.files:
            file = request.files['file']
            if file.filename:
                try:
                    # Spara filen och uppdatera todo med filinformation
                    blob_path = f'todo_files/{safe_login_name}/{todo_id}/{file.filename}'
                    blob = bucket.blob(blob_path)
                    
                    content_type = file.content_type or 'application/octet-stream'
                    metadata = {
                        'original_filename': file.filename,
                        'content_type': content_type
                    }
                    blob.metadata = metadata
                    
                    file.seek(0, 2)
                    file_size = file.tell()
                    file.seek(0)
                    
                    blob.upload_from_file(file, content_type=content_type)
                    
                    url = blob.generate_signed_url(
                        version="v4",
                        expiration=timedelta(minutes=15),
                        method="GET"
                    )
                    
                    file_data = {
                        'filename': file.filename,
                        'blob_path': blob_path,
                        'size': file_size,
                        'content_type': content_type,
                        'upload_time': datetime.now(),
                        'download_url': url
                    }
                    
                    todo_ref.update({
                        'files': firestore.ArrayUnion([file_data]),
                        'updated_at': datetime.now()
                    })
                except Exception as e:
                    print(f"Fel vid filuppladdning: {e}")
        
        # Hämta den uppdaterade todo:n för att returnera
        updated_todo = todo_ref.get().to_dict()
        updated_todo['id'] = todo_id
        
        # Konvertera deadline till strängformat om det finns
        if updated_todo.get('deadline'):
            updated_todo['deadline'] = updated_todo['deadline'].strftime('%Y-%m-%d')
        
        return jsonify(updated_todo)
        
    except Exception as e:
        print(f"Fel vid uppdatering av todo: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_todo_files/<todo_id>')
def get_todo_files(todo_id):
    if 'user' not in session:
        return redirect(url_for('index'))
    
    safe_login_name = get_safe_login_name()
    todo_ref = db.collection("users").document(safe_login_name).collection("todos").document(todo_id)
    todo_doc = todo_ref.get()
    
    if todo_doc.exists:
        todo_data = todo_doc.to_dict()
        return jsonify(todo_data.get('files', []))
    
    return jsonify([])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
