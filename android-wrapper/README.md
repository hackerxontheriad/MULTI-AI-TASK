# MAD X Android WebView wrapper source

This is source code, not a compiled APK. Replace `https://YOUR-SERVICE.onrender.com/` in `MainActivity.java` with your deployed HTTPS Render URL, then open this folder in Android Studio and build a signed APK with your own signing key.

This wrapper intentionally disables cleartext traffic, file access, content access, and mixed content. Google OAuth may require testing in Chrome/custom tabs depending on Google Identity Services and WebView behavior. Never embed OAuth client secrets, API tokens, or signing keys in this project.
