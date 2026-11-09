# Meal Roulette for iOS

This is a native SwiftUI client for iOS/iPadOS 17 and newer. It connects directly to a household's local server, including a Tailscale Serve HTTPS address, and uses the same plan, preference, routine, and grocery rules as the web interface. There are no third-party mobile SDKs or vendor accounts.

## Open and run

Open MealRoulette.xcodeproj in Xcode on a Mac. Select the MealRoulette scheme and an iPhone/iPad simulator, then run. On a physical device, select your own signing team and bundle identifier in Xcode; a public App Store release is not part of this repository's unsigned simulator build.

Enter the server's complete http/https address, including a custom port if used. Connect Tailscale on the phone when accessing a tailnet address. Allow local-network access when iOS requests it for a LAN server.

The client supports:

- Creating, choosing, confirming, and revising weekly plans.
- Rerolling or choosing meals and applying eating-out/leftovers labels.
- Per-date diner/effort/theme exceptions and reusable routines.
- Meal details, serving yields, ingredients, household members, and preference lists.
- Shared groceries, purchased/already-owned marks, and manual extras.
- Calendar preview and explicit publication when enabled by the server owner.
- A protected local cache for offline reading. Mutations require a connection; stale revisions are reported without silently retrying over another person's edits.

The saved server address and cache stay on the phone. Disconnecting or clearing the cache does not delete the server's household records. A standalone device-only backend is a separate future edition.

## Build and verify

The checked-in project has a shared scheme and no package dependencies. Its deterministic generator uses only Python:

~~~sh
python3 ios/generate_project.py
xcodebuild -project ios/MealRoulette.xcodeproj -scheme MealRoulette -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
~~~

The GitHub Actions native job starts tests/native_fixture_server.py with synthetic household data, then runs native HTTP integration tests and an iPhone UI test. It uploads the test result bundle, build log, and MealRoulette-Simulator.zip. No production server, provider credentials, or personal household data is used.

To run the tests locally, start the fixture on port 5057 on a Mac, select a simulator, then run the scheme's tests. Use an unused port or stop a local household service first if 5057 is already occupied. The fixture uses a temporary database that is removed when it exits.
