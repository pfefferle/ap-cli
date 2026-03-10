from .command import Command
import webbrowser
import os
import base64
import hashlib
from pathlib import Path
from requests_oauthlib import OAuth2Session
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import urllib
import logging
import urllib.parse
import requests
from ap.version import __version__

CLIENT_ID = "https://evanp.github.io/ap/client.jsonld"
CIMD_ID = "https://evanp.github.io/ap/cimd.json"
REDIRECT_URI = "http://localhost:63546/callback"
SCOPE = "read write"

class LoginRedirectHandler(BaseHTTPRequestHandler):
    login_command: "LoginCommand | None" = None

    def do_GET(self):
        global oauth, token_endpoint, state, verifier, code
        if self.path.startswith("/callback"):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Success</title></head><body><p>You may now close this window.</p></body></html>"
            )
            if (LoginRedirectHandler.login_command is not None):
                LoginRedirectHandler.login_command.on_callback(
                    urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                )

    def log_request(self, code="-", size="-"):
        pass


class LoginCommand(Command):
    def __init__(self, args, env):
        super().__init__(args, env)
        self.id = args.id

    def pkce(self):
        """Generate a PKCE code verifier and challenge

        Returns:
            tuple: A tuple containing the code verifier and challenge
        """
        verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
        challenge = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(challenge).decode("utf-8").rstrip("=")
        return (verifier, challenge)

    def oauth_endpoints(self, json):
        auth_endpoint = self.get_endpoint(json, "oauthAuthorizationEndpoint")
        token_endpoint = self.get_endpoint(json, "oauthTokenEndpoint")
        return (auth_endpoint, token_endpoint)

    def save_token(self, token):
        apdir = Path(self.env.get("HOME")) / ".ap"
        if not apdir.exists():
            apdir.mkdir(700)
        data = {"actor_id": self.actor_id, **token}
        with open(apdir / "token.json", "w") as f:
            f.write(json.dumps(data))

    def discover(self, actor_id):

        parts = self.discover_well_known(actor_id)

        if parts is not None:
            return parts

        parts = self.discover_actor(actor_id)

        if parts is not None:
            return parts

        raise Exception('No OAuth metadata discoverable')

    def discover_well_known(self, actor_id):
        parsed = urllib.parse.urlparse(actor_id)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        metadata_url = f"{origin}/.well-known/oauth-authorization-server"
        user_agent = f"ap/{__version__}"
        headers = {
            "Accept": "application/json",
            "User-Agent": user_agent
        }

        r = requests.get(metadata_url, headers=headers)

        if not r.ok:
            return None

        metadata = r.json()

        # TODO: check for PKCE, authorization code flow, refresh

        if "authorization_endpoint" not in metadata:
            return None

        auth_endpoint = metadata["authorization_endpoint"]

        if "token_endpoint" not in metadata:
            return None

        token_endpoint = metadata["token_endpoint"]

        if "client_id_metadata_document_supported" in metadata and \
            metadata["client_id_metadata_document_supported"]:
            client_id = CIMD_ID
        elif "activitypub_object_id_as_client_id" in metadata and \
            metadata["activitypub_object_id_as_client_id"]:
            client_id = CLIENT_ID
        else:
            return None

        return (client_id, auth_endpoint, token_endpoint)

    def discover_actor(self, actor_id):

        actor = self.get_public(actor_id)

        if "objectIDAsClientID" in actor and actor["objectIDAsClientID"]:
            client_id = CLIENT_ID
        else:
            return None

        (auth_endpoint, token_endpoint) = self.oauth_endpoints(actor)

        return (client_id, auth_endpoint, token_endpoint)

    def run(self):
        """Log into an ActivityPub server

        Args:
            id (str): The ID of the user to login as; either an
                ActivityPub ID or a webfinger address
        """

        self.actor_id = self.get_actor_id(self.id)

        (client_id, auth_endpoint, token_endpoint) = \
            self.discover(self.actor_id)

        self.token_endpoint = token_endpoint

        (verifier, challenge) = self.pkce()

        self.verifier = verifier

        self.oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, scope=SCOPE)
        authorization_url, state = self.oauth.authorization_url(
            auth_endpoint, code_challenge=challenge, code_challenge_method="S256"
        )

        self.state = state

        webbrowser.open(authorization_url)

        # Processing continues in on_callback()

        LoginRedirectHandler.login_command = self

        server = HTTPServer(("localhost", 63546), LoginRedirectHandler)
        server.handle_request()  # To handle only the first request
        server.server_close()

    def on_callback(self, qs):
        state = qs.get("state", None)
        if state is None or self.state != state[0]:
            raise Exception("State mismatch")
        error = qs.get("error", None)
        if error is not None:
            error_val = error[0]
            if error_val == "access_denied":
                print("Access denied")
            else:
                print(f"Error: {error_val}")
                return
        codes = qs.get("code", None)
        if codes is None:
            raise Exception("No code found")
        code = codes[0]
        token = self.oauth.fetch_token(
            self.token_endpoint,
            code=code,
            code_verifier=self.verifier,
            include_client_id=True,
        )
        self.save_token(token)
