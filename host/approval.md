# Home Assistant approval route

[Host deployment and checks](README.md)

The route receives a question and returns its decision. Update it before requesters that require its explicit `{"accepted": true}` receipt. Questions are bounded before notification. It never receives a 1Password token or resolves a secret. The requester gets two narrow webhook URLs and an answer credential, not a Home Assistant login token. The question webhook uses its unpredictable URL as its credential. The answer webhook also requires the bearer credential. Both URLs and the credential must stay private. Each webhook ID and the credential must contain at least 32 characters. Generate independent unpredictable values outside an agent session.

After the first plain-HA deployment, the operator creates their Home Assistant account and registers the intended companion devices through the desktop and phone apps. Open Settings > People > Users and select that operator's account. Copy its user ID, shown as `ID`, as [Home Assistant documents](https://www.home-assistant.io/integrations/person/#configuration-variables). Use the user ID, not a person or entity ID. Enable Advanced mode in the profile if the Users tab is hidden. Use only the intended operator's notification services.

At the host desk, the operator creates `/srv/homeassistant/config/secrets.yaml` under root ownership with mode `0600`. Use the configured deployment directory if it differs. Enter these settings locally, outside agent tools. These placeholders are not credentials:

```yaml
secret_approval_route_ask_url: https://YOUR_CERTIFICATE_NAME/api/webhook/YOUR_RANDOM_ASK_ID
secret_approval_route_answer_url: https://YOUR_CERTIFICATE_NAME/api/webhook/YOUR_RANDOM_ANSWER_ID
secret_approval_route_credential: YOUR_RANDOM_ANSWER_CREDENTIAL
secret_approval_route_operator: YOUR_HOME_ASSISTANT_USER_ID
secret_approval_route_devices:
  - mobile_app_YOUR_PHONE
```

Rerun `host:ha:deploy` with the same reviewed revision and private settings paths. The role inspects only file metadata, with checksum, MIME and attribute reads disabled. It refuses a nonregular, empty, non-root-owned or non-`0600` file before changing ownership. No playbook generates, reads, copies or transports credentials. If a previously installed approval package loses its settings, deployment refuses before a restart. Metadata checks cannot validate the contents. Check the HA startup log at the desk for configuration errors without sharing private settings.

Configure the requester through the [two-tier setup guide](../docs/1password-access.md). Its `home-assistant.json` uses `ask_url`, `answer_url` and `token`. The `token` is the same answer credential stored above. That credential belongs to this route only. Never substitute a Home Assistant long-lived access token. Outside agent tools, the operator first stores the two route URLs and the answer credential in their own 1Password route item. Then they put references to those three fields in their private copy of `examples/op-approval.env.example` and run the documented setup command. The env file contains references only.

A notification body tap opens the request on the approval page. Only the configured operator's authenticated Home Assistant user can read waiting questions or decide them. The notification and page bind each decision to one question ID and one sending token. The first valid decision wins. Ten minutes without a valid decision expires the question. Decisions remain readable for fifteen minutes from the question's creation. Restarting Home Assistant loses pending requests, so requesters must ask again. The panel writes question text as text. No sensor or recorder history stores waiting question details. Route logs omit webhook IDs, action tokens and companion registration error details.

With a throwaway secret, perform the [operator route checks](../docs/1password-access.md#prove-the-route) for Approve, Deny, expiry, body taps, duplicate decisions, wrong-user refusal and restart. Confirm that the answer credential is refused by unrelated HA APIs. Static handler tests and `check_config` do not prove those live authentication or notification boundaries. Confirm the ordinary agent account cannot read `secrets.yaml` or HA registration storage. Root and Docker administrators remain trusted.

For rotation, the operator replaces the route values at the desk and reruns the intended HA deployment, then updates each requester's route through the setup guide. Verify a throwaway approval. A route failure runs no waiting command. Only an explicit operator instruction selects the desktop fallback described in the secret guide.

When upgrading a previous broker installation, the operator stops and disables that retired service and removes its old bootstrap credentials through their normal credential-revocation process. This deployment removes only the retired managed panel files. It does not stop or delete an existing broker, migrate credentials or revoke them. Complete that operator migration before relying on the new route.
