"""Alias „sonnet“ wird beim Anthropic-Backend zum aktuellen Sonnet; ein ausdrücklicher Modellname bleibt."""
from unittest import mock

from belege import urteil


def _modell_im_aufruf(modell: str) -> str:
    with mock.patch.object(urteil.requests, "post") as post:
        post.return_value = mock.Mock(status_code=200, json=lambda: {"content": [{"text": "x"}]})
        urteil._anthropic_post("sk-test", "auftrag", modell)
        return post.call_args.kwargs["json"]["model"]


def test_alias_sonnet_wird_aktuelles_sonnet():
    assert _modell_im_aufruf("sonnet") == "claude-sonnet-5-5"


def test_ausdruecklicher_modellname_bleibt():
    assert _modell_im_aufruf("claude-sonnet-5") == "claude-sonnet-5"
