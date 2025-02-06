from flask import Flask, render_template, request, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, auth, storage
import os

app = Flask(__name__)
app.secret_key = 'super-hemligt-nyckel'  # OBS: Byt ut mot en stark hemlighet i produktion

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
    'storageBucket': firebase_storage_bucket  # Exempel: "template-d8a76.firebasestorage.app"
})
bucket = storage.bucket()

# Konstruera Firebase-konfigurationen som ett dictionary
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
    # Skicka Firebase-konfigurationen till index.html
    return render_template("index.html", firebase_config=firebase_config)

@app.route('/login', methods=['POST'])
def login():
    # Ta emot ID-token från klienten och verifiera den
    id_token = request.form.get("idToken")
    if id_token:
        try:
            decoded_token = auth.verify_id_token(id_token)
            session['user'] = decoded_token
            print(f"Användare inloggad: {decoded_token.get('email')} (UID: {decoded_token.get('uid')})")
            return redirect(url_for('dashboard'))
        except Exception as e:
            print("Token-verifiering misslyckades:", e)
            return "Ogiltig token", 400
    return "Token saknas", 400

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        return render_template("dashboard.html", user=session['user'])
    else:
        return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        if 'file' not in request.files:
            return "Ingen fil skickades", 400
        file = request.files['file']
        if file.filename == '':
            return "Ingen fil vald", 400
        if file:
            user = session['user']
            # Hämta inloggningsnamnet (t.ex. e-post) och sanera det så att det är säkert att använda i en sökväg
            login_name = user.get('email')
            safe_login_name = login_name.replace('@', '_').replace('.', '_') if login_name else 'unknown'
            # Skapa blob-sökvägen: csv_uploads/<safe_login_name>/<filnamn>
            blob_path = f'csv_uploads/{safe_login_name}/{file.filename}'
            blob = bucket.blob(blob_path)
            blob.upload_from_file(file)
            return f"Filen laddades upp och sparades i mappen {safe_login_name}!"
    return render_template("upload.html")

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # För repl.it: kör applikationen på host '0.0.0.0' och port 3000
    app.run(host='0.0.0.0', port=3000, debug=True)
