# Profile components

One section per block of `/profile`: AccountSection (`PATCH /auth/me`), PhoneSection (the number critical alerts are texted to), PasswordSection (`POST /auth/change-password`), TwoStepSection (`/auth/2fa/*`), ProvidersSection (Google, GitHub and Microsoft sign-in) and DataSection (`GET /auth/me/export`). Section.tsx is the shared heading and result line. types.ts holds the shape of `GET /auth/me`.
