# Preserved verification attempts
1. Adapter-only QA against pre-existing user services: Goal workflow visibly
   SUCCEEDED with two bound MOCK results. Test failed reading collapsed pre via
   innerText (empty string). Application success was observed; structured export
   was not completed by this attempt. Backend evidence remains preserved.
2. Correcting that test exposed Windows cp1252 default encoding in a source write;
   write_text truncated new app.js before raising UnicodeEncodeError. A subsequent
   browser test correctly failed at Checking connection. No canonical backend file
   changed. Script restored via explicit UTF-8 atomic write before further tests.
These attempts are not a passing full browser test and are not hidden by final QA.
