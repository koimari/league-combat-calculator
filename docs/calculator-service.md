# Calculator service access

The Scryglass server proxy calls the Flask calculator with
`Authorization: Bearer <token>`. Configure the same random secret in each
server's `CALCULATOR_SERVICE_TOKEN` environment variable. Use at least 32
characters and HTTPS for the upstream connection. Keep the token in server
configuration and out of browser bundles, URLs, response bodies, and logs.

`src/service_auth.py` lists the permitted method/path pairs. Access covers
calculator catalogs, calculation, comparison, BIS, and optimization. These
requests retain their existing validation, result-cache, and rate policies.
The token grants no access to sharing, saved builds, administrative routes,
data updates, or the HTML interface.

An attempted bearer request with an invalid token, a missing or short configured
secret, or an unsupported method/path receives JSON HTTP 401. This check also
applies when `SCRYGLASS_AUTH_REQUIRED` is disabled. Requests without a bearer
header follow the existing browser cookie policy. A valid browser session
does not rescue an invalid bearer header.

The Next proxy should allow the same explicit route list, forward query
parameters only for those routes, retain upstream status and `Retry-After`,
and enforce the Flask 32 KiB request limit. It should reject unexpected login
redirects and forward only approved response headers. Browser cookies and
caller-supplied upstream URLs are unnecessary for this service contract.
