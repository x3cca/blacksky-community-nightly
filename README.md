# Blacksky Android Nightly

> [!WARNING]
> **Unofficial** automated nightly builds of
> [blacksky-algorithms/blacksky.community](https://github.com/blacksky-algorithms/blacksky.community)
> `main`. Not endorsed by Blacksky Algorithms; may be unstable.

## Install with Obtainium

- Repository URL: `https://github.com/x3cca/blacksky-community-nightly`
- Asset regex: `blacksky-nightly-universal\.apk`

The app ID is `community.blacksky.app.nightly`, so it installs alongside the
official app with separate data. Every release is signed with the same key, so
updates install normally.

## How it works

This repo contains no app source, only:

- `.github/workflows/nightly.yml`: runs daily at 09:20 UTC (or by hand). It skips
  if upstream `main` is already released, otherwise checks out upstream, applies
  the overlay, builds a release APK, signs it, and publishes a GitHub release.
  It keeps the newest 30 releases.
- `nightly/apply.sh`: the overlay. It wraps upstream's `app.config.js` with
  `nightly/app.config.js` (name, app ID, version, icon, OTA updates off) and
  works around upstream asset quirks.

Test the overlay locally:

```sh
git clone https://github.com/blacksky-algorithms/blacksky.community /tmp/up
nightly/apply.sh /tmp/up && git -C /tmp/up diff
```

Signing uses the secrets `NIGHTLY_KEYSTORE_B64`, `NIGHTLY_KEYSTORE_PASSWORD`,
`NIGHTLY_KEY_ALIAS`, and `NIGHTLY_KEY_PASSWORD`. The variable
`NIGHTLY_CERT_SHA256` pins the expected signer.
