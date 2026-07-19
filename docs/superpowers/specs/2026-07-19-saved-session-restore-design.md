# Saved Session Restore Design

## Goal

Resume a valid DPAPI-protected Buckler session when the desktop app starts, avoiding repeated user-code entry and browser login.

## Scope

- Add a read-only native bridge status method that reports the projected 10-digit user code when available, plus whether a valid saved session exists.
- Restore that state once pywebview is ready.
- Autofill the returned code, enable collection only with a verified session, and change the login action to its existing Korean re-login label.
- Preserve a valid projected code even when the saved session has expired, so the user can choose re-login without retyping it.

## Security and data handling

Browser storage state stays solely in `DpapiAuthVault`. No cookie, URL, exception text, or storage-state data is sent to JavaScript. The native response contains only `ok`, `authenticated`, `user_code`, and optional `code`. The optional code is exactly `AUTH.SESSION_UNAVAILABLE`; every vault or internal probe failure is normalized to it.

## Data flow

1. The dashboard waits for `pywebviewready` and starts at most one status probe.
2. It calls `auth_status()` on the native bridge.
3. The bridge returns the valid projected code if it is available. It sets `authenticated` only when `auth_state == VALID`, the projected code is syntactically a 10-digit code, the DPAPI vault is readable, and the vault code exactly matches the projection.
4. For an authenticated response, the dashboard autofills and protects the code, enables collection, and presents the re-login action.
5. For an unauthenticated response with a projected code, the dashboard prefills the code but keeps collection disabled. For no code, it retains the manual-login state.
6. A successful new login establishes authenticated state locally without an app restart.

The probe is read-only: it never opens a browser or changes account state. Collection stays disabled while probing. A delayed probe result is ignored if a later successful login established authenticated state.

## Error handling

The UI never receives raw native errors. Any unavailable, invalid, or unreadable saved session follows the normal re-login-needed path. Collection stays disabled until a verified restoration or successful login.

## Validation

Manual validation requested by the user: after one successful login, fully restart the app and confirm the code is prefilled, collection is enabled, and no browser opens unless the re-login action is selected. Automated test execution remains deferred to the user.
