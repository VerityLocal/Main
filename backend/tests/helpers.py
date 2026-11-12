"""Explicit test credentials; production always requires local configuration."""

from dataclasses import replace
from fastapi.testclient import TestClient as BaseClient
from backend.app import create_app as real_create_app
from backend.config import Settings

TOKEN = 'test-only-' + 'a'*40


def create_app(settings=None, **kwargs):
    return real_create_app(replace(settings or Settings(), auth_token=TOKEN), **kwargs)


class TestClient(BaseClient):
    def __init__(self, app, **kwargs):
        headers = {'Authorization':'Bearer '+TOKEN, **kwargs.pop('headers', {})}
        super().__init__(app, headers=headers, **kwargs)
