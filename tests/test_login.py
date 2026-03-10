import unittest
from unittest.mock import patch, mock_open, MagicMock
from ap.main import run_command
from argparse import Namespace
import io
import sys
import requests
from requests_oauthlib import OAuth2Session
import json
from ap.version import __version__
import logging
import webbrowser
import threading
import time
import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode, quote
from pathlib import Path

USER_AGENT = f"ap/{__version__}"

AUTHORIZATION_ENDPOINT = "https://social.example/oauth/authorization"
TOKEN_ENDPOINT = "https://social.example/oauth/token"

ACTOR_ID = "https://social.example/users/evanp"
ACTOR = {
    "type": "Person",
    "id": ACTOR_ID,
    "outbox": "https://social.example/users/evanp/outbox",
    "endpoints": {
        "oauthAuthorizationEndpoint": AUTHORIZATION_ENDPOINT,
        "oauthTokenEndpoint": TOKEN_ENDPOINT
    },
    "objectIDAsClientID": True
}

ACTOR_WEBFINGER_ID = "evanp@social.example"

WEBFINGER_URL_BASE = "https://social.example/.well-known/webfinger"
ACTOR_WEBFINGER_URL = WEBFINGER_URL_BASE + "?resource=acct%3Aevanp%40social.example"

ACTOR_WEBFINGER_JSON = {
    "subject": "acct:evanp@social.example",
    "links": [{"rel": "self",
               "type": "application/activity+json",
               "href": ACTOR_ID}]
}

AUTHORIZATION_CODE = '1234567890ABCDEF'
ACCESS_TOKEN = {
    "access_token": 'XYZPDQ',
    "token_type": 'Bearer',
    "scope": 'read write',
    "expires_in": 86400,
    "refresh_token": 'OMGBBQ'
}

CIMD_AUTHORIZATION_ENDPOINT = "https://cimd.example/oauth/authorization"
CIMD_TOKEN_ENDPOINT = "https://cimd.example/oauth/token"
CIMD_CLIENT_ID = "https://evanp.github.io/ap/cimd.json"

CIMD_ACTOR_ID = "https://cimd.example/users/other"
CIMD_ACTOR = {
    "type": "Person",
    "id": CIMD_ACTOR_ID,
    "outbox": "https://cimd.example/users/other/outbox",
    "inbox": "https://cimd.example/users/other/inbox"
}

CIMD_ACTOR_WEBFINGER_ID = "other@cimd.example"
CIMD_WEBFINGER_URL_BASE = "https://cimd.example/.well-known/webfinger"
CIMD_ACTOR_WEBFINGER_URL = CIMD_WEBFINGER_URL_BASE + "?resource=" + quote('acct:' + CIMD_ACTOR_WEBFINGER_ID)

CIMD_ACTOR_WEBFINGER_JSON = {
    "subject": "acct:" + CIMD_ACTOR_WEBFINGER_ID,
    "links": [{"rel": "self",
               "type": "application/activity+json",
               "href": CIMD_ACTOR_ID}]
}

CIMD_METADATA_URL = "https://cimd.example/.well-known/oauth-authorization-server"

CIMD_METADATA_JSON = {
  "issuer": "https://cimd.example",
  "authorization_endpoint": CIMD_AUTHORIZATION_ENDPOINT,
  "token_endpoint": CIMD_TOKEN_ENDPOINT,
  "scopes_supported": [
    "read",
    "write"
  ],
  "response_types_supported": [
    "code"
  ],
  "grant_types_supported": [
    "authorization_code",
    "refresh_token"
  ],
  "code_challenge_methods_supported": [
    "S256"
  ],
  "token_endpoint_auth_methods_supported": [
    "none"
  ],
  "client_id_metadata_document_supported": True
}

def mock_requests_get(url, **kwargs):
    if url == WEBFINGER_URL_BASE:
        return MagicMock(
            status_code=200,
            headers={"Content-Type": "application/jrd+json"},
            json=lambda: ACTOR_WEBFINGER_JSON,
        )
    elif url == ACTOR_ID:
        return MagicMock(status_code=200,
                         headers={"Content-Type": "application/activity+json"},
                         json=lambda: ACTOR
                         )
    elif url == CIMD_WEBFINGER_URL_BASE:
        return MagicMock(
            status_code=200,
            headers={"Content-Type": "application/jrd+json"},
            json=lambda: CIMD_ACTOR_WEBFINGER_JSON,
        )
    elif url == CIMD_METADATA_URL:
        return MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json=lambda: CIMD_METADATA_JSON,
        )
    elif url == CIMD_ACTOR_ID:
        return MagicMock(status_code=200,
                         headers={"Content-Type": "application/activity+json"},
                         json=lambda: CIMD_ACTOR
                         )
    else:
        return MagicMock(status_code=404)

def mock_oauth_request(url, **kwargs):
    if url == TOKEN_ENDPOINT:
        return MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps(ACCESS_TOKEN)
        )
    elif url == CIMD_TOKEN_ENDPOINT:
        return MagicMock(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps(ACCESS_TOKEN)
        )
    else:
        return MagicMock(status_code=404)

authorization_params = None
web_response = None

def mock_webbrowser_open(url):
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if base_url == AUTHORIZATION_ENDPOINT or base_url == CIMD_AUTHORIZATION_ENDPOINT:
        global authorization_params
        authorization_params = parse_qs(parsed.query)
        redirect_uri = authorization_params["redirect_uri"][0]
        def delayed_callback():
            time.sleep(0.1)
            assert authorization_params is not None
            params = {
                "code": AUTHORIZATION_CODE,
                "state": authorization_params['state'][0]
            }
            uri = redirect_uri + "?" + urlencode(params)
            with urllib.request.urlopen(uri) as response:
                global web_response
                web_response = response.read()
        threading.Thread(target=delayed_callback).start()

class TestLoginCommand(unittest.TestCase):
    def setUp(self):
        self.held, sys.stdout = sys.stdout, io.StringIO()  # Redirect stdout

    def tearDown(self):
        sys.stdout = self.held

    @patch.object(Path, 'mkdir')
    @patch("builtins.open", new_callable=mock_open)
    @patch('webbrowser.open', side_effect=mock_webbrowser_open)
    @patch('requests.get', side_effect=mock_requests_get)
    @patch("requests_oauthlib.OAuth2Session.request", side_effect=mock_oauth_request)
    def test_login(self, mock_requests_post, mock_requests_get, mock_webbrowser_open, mock_file, mock_path_mkdir):
        run_command(["login", ACTOR_WEBFINGER_ID], {'LANG': 'en_CA.UTF-8', 'HOME': '/home/notauser'})

        # Assertions
        self.assertGreaterEqual(mock_requests_get.call_count, 1)
        self.assertGreaterEqual(mock_requests_post.call_count, 1)
        mock_webbrowser_open.assert_called_once()

        global authorization_params
        assert authorization_params is not None
        assert "client_id" in authorization_params

        mock_file.assert_called_once_with(Path('/home/notauser/.ap/token.json'), 'w')

    @patch.object(Path, 'mkdir')
    @patch("builtins.open", new_callable=mock_open)
    @patch('webbrowser.open', side_effect=mock_webbrowser_open)
    @patch('requests.get', side_effect=mock_requests_get)
    @patch("requests_oauthlib.OAuth2Session.request", side_effect=mock_oauth_request)
    def test_login_cimd(self, mock_requests_post, mock_requests_get, mock_webbrowser_open, mock_file, mock_path_mkdir):

        run_command(["login", CIMD_ACTOR_WEBFINGER_ID], {'LANG': 'en_CA.UTF-8', 'HOME': '/home/notauser'})

        # Assertions
        self.assertGreaterEqual(mock_requests_get.call_count, 1)
        self.assertGreaterEqual(mock_requests_post.call_count, 1)
        mock_webbrowser_open.assert_called_once()

        global authorization_params
        assert authorization_params is not None
        assert "client_id" in authorization_params

        urls_fetched = [call.args[0] for call in mock_requests_get.call_args_list]
        self.assertIn(CIMD_METADATA_URL, urls_fetched)

        self.assertEqual(authorization_params["client_id"][0], CIMD_CLIENT_ID)

        mock_file.assert_called_once_with(Path('/home/notauser/.ap/token.json'), 'w')