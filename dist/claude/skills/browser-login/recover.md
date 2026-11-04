# Browser login recovery

The [skill](SKILL.md) owns the procedure. This file says what a failure means and what to do next.

## Failures

| Result | Meaning | Next |
|---|---|---|
| `BROWSER_TAB_LOST` | Chrome took the tab away from this session, and the real page stays open outside it. Chrome does this when a page holds a frame of another extension, and it refuses to reconnect while that frame exists. The route blocks 1Password's frames, so suspect a 1Password update or another extension. That stays a hypothesis until proven. `go-back` past the first page also lands here, because every tab starts blank, and its `tabs_left` is then a false alarm | Close the state and report the result, the address and the time. A new `start` would leave another tab behind |
| `BROWSER_PAGE_NOT_REACHED` | `start` opened a tab, but no page arrived at the end. The reason follows the result | Close the state. Start once more only if the reason names a passing fault such as a network error |
| `BROWSER_START_FAILED` | A start step failed. The result carries the page tool's error | Close the state. The start limit applies |
| `BROWSER_CONNECTION_LOST` | The session ended. No credential field is involved | Close the state. The start limit applies |
| `BROWSER_PAGE_REFUSED: the page does not answer` | The guard could not read the page, so it refused the page tool | Repeat once. If it persists, close the state and report it |
| `BROWSER_PAGE_REFUSED: a credential field holds a value` | A field really holds a value | Use `fill`, or close the state and report it |

## Credential results

If the result says `phase: preflight`, its `step` is the page that did not match. With `step` 0 and `credential_input: false`, nothing was entered, so correct the selector and request a new attempt. With a later step, inspect the current page before anything else. Correct the login file and request a new attempt only from an observed page, never by repeating a submitted step. For any other failed or uncertain credential result, preserve its diagnostic and never resubmit. A narrow read may establish completion despite a lost reply. Otherwise close the state and report the unknown result or refusal. Never print raw replies or inspect filled controls.

## Other recovery

A signed-out service is no failure. Use [Log in](SKILL.md#log-in) with the required command order and Home Assistant approval. Do not ask for hand login merely because a session expired.

An interrupted task can leave its tab open and its session attached. Close its recorded state. Never close a state another session started.

## Keep the login file correct

Keep the service flow in its owning vault note. If the plot already uses `fields/<plot>/logins.md`, use that file. Read only the notes for this task.

```markdown
## <Service>
Start: <address>
Creds: <op references, never values>
Flow: <each page's URL, selectors and control>
Proof: <what shows a real login, for this service>
Reach: agent | operator only | item missing
Notes: <what surprised the last session>
```

After a first successful login that the operator ordered, update the service's existing note using the entry format above. After a failed or changed login, correct the flow, proof and notes in the vault. A new host or credential reference needs the operator's word.
