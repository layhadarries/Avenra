# Avenra missing backend modules — restore only

This package adds 40 missing Python modules under avenra/, plus six backend
package tests. It restores the OOP implementation from your latest uploaded
proj-mock-up-main(1).zip, changing package references from safepath to avenra.
It does not replace your existing app.py, config, controllers, database helpers,
templates, static files or current tests.

## Apply in Fish

From your Avenra project folder, use unzip's no-overwrite option:

    unzip -n ~/Downloads/avenra-backend-restore.zip -d /home/tazio/Desktop/Avenra
    python -m unittest discover -s tests -p 'test_backend_package.py' -v
    python -m unittest discover -s tests -p 'test_*.py' -v

Adjust the Downloads path if your browser saved it elsewhere. No secret or
database is included. The tests use temporary databases and disable notification
providers in their subprocesses. Run inside your installed project environment.

## Evidence and limitations

Verified using Python 3.12 and your pushed commit
eae04f3ba2b96bc4d0bef871bdaed3b240d61c85, with the package rename applied in a
separate local check copy. Your uncommitted local edits were not accessible.

All six package/startup tests failed before restoring the missing modules; all
six pass afterward. They verify startup, no normal-mode seeding, secret/cookie
startup guards, signed-out API access denial, and explicit evaluation setup.

The complete current suite runs 30 tests in that check copy: 23 pass, 4 fail and
3 error. The remaining failures are caused by the pushed empty
templates/login.html and static/survivor/index.html (missing login CSRF form and
missing PWA content). Several other frontend test files are empty too.
The full suite is NOT green, and Stage 0 has NOT been merged or tagged.
Frontend work remains with the teammate; this restore does not invent it.

## Security status

This is a structural restore, not security certification or real-data approval.
It retains the uploaded prototype's existing behaviour. Previously confirmed
consent-read authorization, administrator self-grant policy, shared device
identity, evidence validation, encryption/key handling and browser data
lifecycle gaps remain open.

The agreed invitation/approval flow, password plus email/SMS sign-in, survivor
self-registration/PIN/device authentication, and alert-limited private sharing
are requirements for subsequent implementation. This package does not claim to
implement those flows. Normal startup remains independent of evaluation fixtures.
