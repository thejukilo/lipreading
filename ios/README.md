# Lipreading — native iOS app (SwiftUI)

Phase 1: Supabase auth (email + Sign in with Apple) and the **Speak** loop
(camera → backend → spoken reply). Voices and Teach come in Phase 2.

The Swift sources live in `ios/Lipread/`. You create the Xcode project around
them (Xcode needs to own the `.xcodeproj`), then commit it so **Xcode Cloud** can
build it.

## 1. Create the Xcode project
1. Xcode → **File → New → Project → iOS → App**.
2. Name **Lipread**, Interface **SwiftUI**, Language **Swift**. Save it into the
   `ios/` folder (so the project sits next to `Lipread/`).
3. Delete the auto-generated `ContentView.swift` and `LipreadApp.swift`.
4. **Add** all files from `ios/Lipread/` to the target (drag them in, "Copy items
   if needed" unchecked if they're already under `ios/`).

## 2. Add the Supabase SDK
File → **Add Package Dependencies…** →
`https://github.com/supabase/supabase-swift` → Dependency Rule **Up to Next
Major 2.0.0** → add the **Supabase** library to the Lipread target.

## 3. Capabilities + Info.plist
- **Signing & Capabilities** → select your Team → add capability
  **Sign in with Apple**.
- Set a Bundle Identifier you own, e.g. `com.jukilo.lipread`.
- In **Info** (Info.plist), add:
  - `NSCameraUsageDescription` = "Lipreading reads your lips from the camera."
  - `NSMicrophoneUsageDescription` = "Record a short clip to clone your voice."

## 4. Fill in config
Edit `Config.swift`:
- `supabaseAnonKey` — Supabase → Project Settings → API → **anon public** key.
- `apiBaseURL` — your backend. Start with your **ngrok** URL (PC), switch to the
  **RunPod** URL later. No trailing slash.

## 5. Supabase Apple provider (for Sign in with Apple)
Supabase → Authentication → Providers → **Apple** → enable, and add your app's
**Bundle Identifier** (e.g. `com.jukilo.lipread`) to **Authorized Client IDs**.
For native iOS that's all it needs (the app sends an Apple identity token).
Email/password can stay enabled too.

## 6. Run on a real device
Plug in your iPhone, select it as the run target, **Run**. (The Simulator has no
camera — Speak needs a device.) Grant camera access when asked, hold the button,
mouth a sentence.

> The backend must be reachable at `apiBaseURL`. For local dev, keep your PC
> server + ngrok running, and set `apiBaseURL` to the ngrok https URL. The app
> sends the Supabase access token; the backend verifies it via `SUPABASE_URL`
> (so run the server with `SUPABASE_URL` set — see docs/cloud-deploy.md).

## 7. Xcode Cloud
1. Commit the whole project (the `.xcodeproj`, sources, and SPM resolution).
2. Xcode → **Product → Xcode Cloud → Create Workflow**, pick this repo/branch and
   the **Lipread** scheme. A build-on-push workflow + TestFlight archive is a good
   start.
3. Xcode Cloud manages signing with your Apple Developer account. First TestFlight
   build lets you install on your phone without a cable.

## Notes / gotchas
- Front-camera preview is mirrored (cosmetic); uploaded frames are un-mirrored,
  which is what the model expects.
- If you enabled **email confirmation** in Supabase, sign-up returns "check your
  email" until confirmed — disable it under Auth → Providers → Email for faster
  testing.
- Strict Swift 6 concurrency may flag a few spots; the project targets the
  default Swift 5 language mode.
