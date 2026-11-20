# Browser login credential steps

The [skill](SKILL.md) owns the procedure and its limits. This file owns the credential steps.

Start at the service's address in the login file. If the page is already signed in, skip to the proof. Otherwise read the file's flow and inspect each page you can reach. The model supplies references and selectors. The session's op resolves values directly to this consumer, which fills the page without native typing. Do not describe this as the model receiving or typing a password. A native permission refusal is still binding.

Create an owner-only env file outside Git with the references of the whole login, using `BROWSER_LOGIN_USERNAME`, `BROWSER_LOGIN_PASSWORD` or `BROWSER_LOGIN_OTP`. Never put resolved values in a command, file, message or model tool argument. One `fill` takes up to four `--step` values in page order, so one approval covers the whole login. Each step names that page's exact URL, up to two fields and the control to press.

```sh
op tier-two --reason "Log into the authorized service for the requested browser task" -- \
  op run --env-file=<reference-file> -- python3 <entry> fill <state> \
  --step '{"url": "https://service.example/login", "fields": [["<username-selector>", "BROWSER_LOGIN_USERNAME"]], "submit": "<continue-selector>"}' \
  --step '{"url": "https://service.example/password", "fields": [["<password-selector>", "BROWSER_LOGIN_PASSWORD"]], "submit": "<submit-selector>"}' \
  --step '{"url": "https://service.example/code", "fields": [["<code-selector>", "BROWSER_LOGIN_OTP"]], "submit": "<verify-selector>"}'
```

Before you ask for approval, send the same steps through `check`, which needs no `op` and no secret:

```sh
python3 <entry> check <state> --step '<the first step>' --step '<the second step>' --step '<the third step>'
```

`check` tests the session and the page in front of it. `BROWSER_FILL_READY` means `fill` can start. Any other result cost no approval, so resolve it and never request approval over it.

The operator's "log into <service>" is the order for the `fill` command. For a tier-one item, drop the `op tier-two --reason "<one line>" --` prefix. Allow ten minutes for approval plus the browser operation. If needed, use native managed background execution and collect that same process. Never duplicate a pending request.

Passkeys are not supported yet. Use the service's password and code when offered, otherwise report the login as operator only. Never create, register or remove a passkey.

Declare only the pages the service shows. Use `BROWSER_LOGIN_OTP` for a generated one-time code in a `text`, `tel`, `number` or `password` field. Use a reference with `?attribute=otp` to generate the code after approval. Keep the chain together and never pass a seed. A later step waits up to 15 seconds for its page. An unused code is harmless.

Some code pages split the code over several boxes, one per digit or one per group of digits. For such a page, name the boxes as a list of exact selectors in code order instead of one selector, for example `[["#digit-1", "#digit-2", "#digit-3", "#digit-4", "#digit-5", "#digit-6"], "BROWSER_LOGIN_OTP"]`. The consumer gives each box an equal part of the code in order, so the list has 2, 3, 4, 6 or 8 boxes and the box count must divide the code length. Each box gets the checks of a single field. Name each box by a stable attribute such as its id, never by its state such as `:enabled`, so the consumer still finds the box to empty it. One selector on such a page fails with `FIELD_CHANGED`.

For an Apple sign-in, let the operator check the prompt and enter the code on their own device. Resume only after they confirm the sign-in finished. Keep the code outside screenshots, tool commands, chat and evidence.

A login form can sit in an embedded frame from another origin, which `snapshot` shows. For such a page, add `"frame": "<frame-address>"` to its step. `url` stays the tab's address. `frame` is the exact address of the frame that holds the fields and the control, and the selectors name elements inside it. Read it with `eval '() => [...document.querySelectorAll("iframe")].map(frame => frame.src)'`. The consumer uses only the one direct child frame of the tab at that origin and path, and `FRAME_UNAVAILABLE` means none or several matched. It also checks that the tab stays on `url` and that nothing on the tab covers the frame's fields or control.

The consumer finds this session's own tab or popup on the first step's exact URL. Before each step it checks the destination, unique enabled fields and the unobstructed submit control, so no value reaches another host. A submit button may be disabled while fields are empty, but must become enabled within five seconds of input, before the helper verifies the values and clicks it. After each step, on success and on failure, it empties every password and code field it filled that still holds the value. A later page can keep the username field and need its value, as Apple's password page does, so a filled username field is emptied once the whole fill ends, on every result. `BROWSER_LOGIN_SUBMITTED` means the last button was clicked, not that authentication succeeded.

After any other result, follow [Recovery](recover.md#credential-results). Never resubmit from an uncertain result, print raw replies or inspect filled controls.

Every `run` command is refused while a password or code field holds a value, or while the page does not answer, because the page tool saves a snapshot after each action. An action can make Chrome reveal a saved password, and then its output is withheld. `fill` still works on that page. If the refusal persists, close the state and report it. Never reveal a hidden password, for example through a "show password" control.
