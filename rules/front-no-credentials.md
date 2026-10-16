---
id: front-no-credentials
level: mandatory
applies_to: {roles: [front]}
enforced_by: [review]
---
# No credentials in the front end

Code that runs in the browser (or in any client the user controls) never holds a credential: no API key, secret, password, private key or long-lived token, neither in the code nor in what it stores (local storage, cookies readable by scripts, the bundle's configuration).

What needs a credential runs on the server, and the front end calls it there. A short-lived token the server issues for one user, scoped to what that user may do, is not a credential in this sense.

Why: anything sent to a browser can be read by whoever uses it, and a credential found there is a credential leaked.
