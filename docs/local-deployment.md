# Public defaults and local deployment

The tracked `config/app.json` is a portable example. It uses the tool's own
output directory and expects an already running OpenAI-compatible endpoint.
The `runtime/` paths are placeholders for optional user-installed binaries;
no executables or model configuration are shipped. Configure your endpoint
before generation. Validation alone does not contact the endpoint.
Public defaults set `router.auto_start` to false: an unavailable endpoint
returns an error instead of starting a process. Set it to true only when
you have configured the router executable and arguments. Existing configs
that omit the field retain their previous auto-start behavior.

For a local deployment, copy it to `config/app.local.json` and edit that full
configuration. There is no implicit merge. The GUI chooses this file when it
exists; `--config <file>` overrides selection. CLI and PowerShell batch callers
must explicitly select their configuration with `--app-config` or `-AppConfigPath`.
Relative paths are resolved from the selected configuration's directory.

Use `profiles.local/` for local profile copies and point the local config's
`paths.profiles` there. Public H3 configuration expects externally supplied
files under `profiles/h3-system-prompts/`; their filenames are specified in
`profiles/h3.json`. No private prompt content is bundled. Plain mode needs none.

Offline example from the tool root:

```powershell
python batch_cli.py --app-config config/app.json --profile profiles/plain.json --input-manifest examples/plain-input.json --mode default --repeats 1 --max-tokens 64 --model example-model --validate-only
```

Local config, local profiles, GUI state, outputs and runtime binaries are
ignored by Git. Windows packaging copies only public app.json from config,
never app.local.json. Review `git diff` and package contents before publishing.
Do not commit task logs, machine paths or local preference updates to product
documentation. Deployment-specific notes belong in the owning workspace.

Router control is separate from inference. Public defaults set
`router.control_enabled` to false; enable it only for an intended llama-swap
control endpoint. Legacy configs that omit it keep control enabled. The GUI
shows the control address before unloading and never forwards `backend.auth`.
Configure `router.auth` separately (`none` by default, or `environment` with
`environment_variable`, optional `header` and `prefix`) when control needs auth.
CLI stdout and stderr use UTF-8, including redirected output on Windows.

Optional runtime-version metadata is collected only when router auto-start is
enabled and the request uses the configured backend URL. The local probe has
a 10-second timeout; failure leaves `runtime_version` null without blocking the
batch. This field describes the configured local binary, not a remotely verified
server version.
