"""Actual Stage 4 Edge contracts; reuse the prototype's destination validation."""
from operator_presence import validate_project_url, validate_publishable_key
import requests


class CloudError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('Cloud request rejected' if status < 500 else 'Cloud unavailable')


class CloudClient:
    def __init__(self, url, key):
        self.url = validate_project_url(url)
        self.key = validate_publishable_key(key)
        self.http = requests.Session()

    def post(self, name, body, credential=None):
        headers = {'apikey': self.key}
        if credential:
            headers.update({'x-device-id': credential['credential_id'], 'x-device-secret': credential['secret']})
        response = self.http.post(self.url + '/functions/v1/' + name, headers=headers,
                                  json=body, timeout=(3.05, 8), allow_redirects=False)
        if response.status_code != 200:
            raise CloudError(response.status_code)
        return response.json()

    def close(self):
        self.http.close()
