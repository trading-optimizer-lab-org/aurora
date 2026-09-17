import pytest

from aurora.infra.sp500_megarun.catalog_requester_broker import CatalogBrokerHttpResponse
from tests.test_catalog_requester_broker import _FakeHttp, _client, _private_key


class RevocationHttp(_FakeHttp):
    def __init__(self, status=204):
        super().__init__()
        self.status = status

    def request(self, method, url, *, headers, json_body=None):
        if method == "DELETE" and url == "https://api.github.com/installation/token":
            self.calls.append((method, url))
            assert headers["Authorization"] == "Bearer opaque-installation-token"
            assert json_body is None
            return CatalogBrokerHttpResponse(status_code=self.status, headers={}, json_body=None)
        return super().request(method, url, headers=headers, json_body=json_body)


def test_ephemeral_token_is_revoked_without_deleting_installation():
    http = RevocationHttp()
    client = _client(http, _private_key())
    token = client.installation_token()
    client.revoke_installation_token(token)
    assert http.calls[-1] == ("DELETE", "https://api.github.com/installation/token")
    assert http.issue_posts == 0


@pytest.mark.parametrize("status", [401, 403, 500])
def test_unconfirmed_revocation_is_not_reported_as_success(status):
    client = _client(RevocationHttp(status), _private_key())
    with pytest.raises(ValueError, match="REVOCATION_UNPROVEN"):
        client.revoke_installation_token("opaque-installation-token")


@pytest.mark.parametrize("path", ["/app/installations/123", "/repos/trading-optimizer-lab-org/aurora/issues/77"])
def test_other_delete_endpoints_remain_forbidden(path):
    http = RevocationHttp()
    with pytest.raises(ValueError, match="ENDPOINT_FORBIDDEN"):
        _client(http, _private_key()).request_fixed("DELETE", path, token="opaque")
    assert http.calls == []
