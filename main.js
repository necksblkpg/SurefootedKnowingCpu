// Importera Firebase-moduler (version 9.x, modulär syntax)
import { initializeApp } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-app.js";
import { 
  getAuth, 
  signInWithPopup, 
  GoogleAuthProvider, 
  signOut, 
  onAuthStateChanged 
} from "https://www.gstatic.com/firebasejs/9.23.0/firebase-auth.js";
import { getStorage, ref, uploadBytes } from "https://www.gstatic.com/firebasejs/9.23.0/firebase-storage.js";

// Din Firebase-konfiguration (byt ut med dina egna uppgifter)
const firebaseConfig = {
  apiKey: "DIN_API_KEY",
  authDomain: "DIN_AUTH_DOMAIN",
  projectId: "DITT_PROJECT_ID",
  storageBucket: "DIN_STORAGE_BUCKET",
  messagingSenderId: "DIN_MESSAGING_SENDER_ID",
  appId: "DIN_APP_ID"
};

// Initiera Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();
const storage = getStorage(app);

// Vänta tills DOM är laddad
window.addEventListener("DOMContentLoaded", () => {
  // Hämta referenser till HTML-element
  const signInButton = document.getElementById("sign-in");
  const signOutButton = document.getElementById("sign-out");
  const fileInput = document.getElementById("file-input");
  const uploadButton = document.getElementById("upload-button");
  const statusText = document.getElementById("status");

  // Funktion för att logga in med Google
  signInButton.addEventListener("click", () => {
    signInWithPopup(auth, provider)
      .then((result) => {
        const user = result.user;
        statusText.textContent = "Inloggad som: " + user.displayName;
      })
      .catch((error) => {
        console.error(error);
        statusText.textContent = "Fel vid inloggning.";
      });
  });

  // Funktion för att logga ut
  signOutButton.addEventListener("click", () => {
    signOut(auth)
      .then(() => {
        statusText.textContent = "Utloggad.";
      })
      .catch((error) => {
        console.error(error);
        statusText.textContent = "Fel vid utloggning.";
      });
  });

  // Funktion för att ladda upp CSV-fil till Firebase Storage
  uploadButton.addEventListener("click", () => {
    const file = fileInput.files[0];
    if (!file) {
      statusText.textContent = "Välj en CSV-fil först.";
      return;
    }
    // Skapa en referens i Storage, t.ex. i mappen "csv-filer/"
    const storageRef = ref(storage, "csv-filer/" + file.name);
    uploadBytes(storageRef, file)
      .then((snapshot) => {
        statusText.textContent = "Fil uppladdad: " + file.name;
      })
      .catch((error) => {
        console.error(error);
        statusText.textContent = "Fel vid uppladdning av fil.";
      });
  });

  // Övervaka inloggningsstatus
  onAuthStateChanged(auth, (user) => {
    if (user) {
      statusText.textContent = "Inloggad som: " + user.displayName;
    } else {
      statusText.textContent = "Ingen inloggad användare.";
    }
  });
});
