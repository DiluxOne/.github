#!/usr/bin/env python3
"""The organisation VM's clock: asks runner-vm.yml to run, on time.

runner-vm.yml starts the VM when a private repository's job waits for it and
deallocates it when idle, but GitHub runs its ten-minute schedule only a few
times a day (#183: 4 to 6 runs of 144 between 10 and 15 October), so a job
that no pull request woke (an issue, a push, a re-run) waited hours. Azure
Functions' timer does run on time: function_app.py calls tick() every five
minutes, and tick() dispatches runner-vm.yml with `auto` as dilux-bot, the
same call runner-wake.yml makes with `start`. The decisions stay in
runner-vm.yml and scripts/runner-demand.sh; this only keeps the time.

Settings of the Function App (diluxone-runner-cl-prod-func):
  DX_BOT_CLIENT_ID        dilux-bot's client ID (the JWT's issuer)
  DX_BOT_INSTALLATION_ID  its installation on the organisation
  DX_BOT_PRIVATE_KEY_B64  its private key, PEM, base64-encoded
  DX_CENTRAL              owner/repo of runner-vm.yml (DiluxOne/.github)

  clock.py --test   self-test (no network, no key)
"""
import base64
import json
import os
import sys
import time
import urllib.request

API = "https://api.github.com"
WORKFLOW = "runner-vm.yml"


def app_jwt(client_id, pem, now, sign):
    """A JWT for the App: issued a minute back for clock drift, ten minutes long."""
    claims = {"iat": now - 60, "exp": now + 540, "iss": client_id}
    return sign(claims, pem)


def rs256(claims, pem):
    import jwt  # PyJWT, only where the key is real

    return jwt.encode(claims, pem, algorithm="RS256")


def request(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def tick(env, now=None, sign=rs256, call=request, action="auto"):
    """Dispatch runner-vm.yml once; returns the dispatch's HTTP status."""
    now = int(time.time()) if now is None else now
    central = env.get("DX_CENTRAL", "DiluxOne/.github")
    pem = base64.b64decode(env["DX_BOT_PRIVATE_KEY_B64"]).decode()
    jwt_token = app_jwt(env["DX_BOT_CLIENT_ID"], pem, now, sign)
    # The installation token reaches only the central repository, only to dispatch.
    _, tok = call(
        "POST",
        f"{API}/app/installations/{env['DX_BOT_INSTALLATION_ID']}/access_tokens",
        jwt_token,
        {"repositories": [central.split("/", 1)[1]], "permissions": {"actions": "write"}},
    )
    status, _ = call(
        "POST",
        f"{API}/repos/{central}/actions/workflows/{WORKFLOW}/dispatches",
        tok["token"],
        {"ref": "main", "inputs": {"action": action}},
    )
    return status


def self_test():
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(("ok  " if cond else "FAIL") + "  " + name)
        fails += 0 if cond else 1

    seen = {}
    claims = app_jwt("Iv-test", "PEM", 1000, lambda c, k: (c, k))
    check("jwt: issued a minute back, expires within ten minutes", claims[0] == {"iat": 940, "exp": 1540, "iss": "Iv-test"})
    check("jwt: signed with the App's key", claims[1] == "PEM")

    calls = []

    def fake(method, url, token, body=None):
        calls.append((method, url, token, body))
        if url.endswith("/access_tokens"):
            return 201, {"token": "ghs_test"}
        return 204, None

    env = {
        "DX_BOT_CLIENT_ID": "Iv-test",
        "DX_BOT_INSTALLATION_ID": "42",
        "DX_BOT_PRIVATE_KEY_B64": base64.b64encode(b"PEM").decode(),
    }
    status = tick(env, now=1000, sign=lambda c, k: seen.setdefault("key", k) and "jwt", call=fake)
    check("tick: the key is decoded before signing", seen.get("key") == "PEM")
    check("tick: dispatch answered 204", status == 204)
    check("tick: token for the installation, as the App", calls[0][:3] == ("POST", f"{API}/app/installations/42/access_tokens", "jwt"))
    check("tick: token limited to .github and actions: write", calls[0][3] == {"repositories": [".github"], "permissions": {"actions": "write"}})
    check("tick: dispatches runner-vm.yml on main with the installation token", calls[1][:3] == ("POST", f"{API}/repos/DiluxOne/.github/actions/workflows/runner-vm.yml/dispatches", "ghs_test"))
    check("tick: with action auto", calls[1][3] == {"ref": "main", "inputs": {"action": "auto"}})

    calls.clear()
    tick(dict(env, DX_CENTRAL="Other/.github"), now=1000, sign=lambda c, k: "jwt", call=fake)
    check("tick: DX_CENTRAL names another organisation's central repository", calls[1][1] == f"{API}/repos/Other/.github/actions/workflows/runner-vm.yml/dispatches")

    print("all passed" if not fails else f"{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    print(tick(os.environ))
