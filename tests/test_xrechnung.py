import subprocess

import pytest

from belege.xrechnung import lesen, sicht_pdf


def test_ubl_lesen(repo):
    p = repo / "u.xml"
    p.write_text(
        "<Invoice><ID>U-1</ID><IssueDate>2026-09-10</IssueDate>"
        "<AccountingSupplierParty><Party><PartyName><Name>Blatt</Name></PartyName>"
        "<PartyTaxScheme><TaxScheme><ID>DE1</ID></TaxScheme></PartyTaxScheme></Party>"
        "</AccountingSupplierParty>"
        "<AccountingCustomerParty><Party><PartyName><Name>Studio Beispiel</Name>"
        "</PartyName></Party></AccountingCustomerParty>"
        '<LegalMonetaryTotal><PayableAmount currencyID="EUR">12.50</PayableAmount>'
        "</LegalMonetaryTotal>"
        "<InvoiceLine><Item><Name>Papier</Name></Item>"
        "<LineExtensionAmount>10</LineExtensionAmount></InvoiceLine></Invoice>"
    )
    d = lesen(p)
    assert d["syntax"] == "ubl"
    assert d["nummer"] == "U-1"
    assert d["betrag"] == 12.5


def test_cii_lesen(repo):
    p = repo / "c.xml"
    p.write_text(
        "<CrossIndustryInvoice><ExchangedDocument><ID>C-1</ID>"
        "<IssueDateTime><DateTimeString>20260910</DateTimeString></IssueDateTime>"
        "</ExchangedDocument><SupplyChainTradeTransaction>"
        "<ApplicableHeaderTradeAgreement>"
        "<SellerTradeParty><Name>Verkauf</Name></SellerTradeParty>"
        "<BuyerTradeParty><Name>Kauf</Name></BuyerTradeParty>"
        "</ApplicableHeaderTradeAgreement><ApplicableHeaderTradeSettlement>"
        "<SpecifiedTradeSettlementHeaderMonetarySummation>"
        '<GrandTotalAmount currencyID="EUR">23.80</GrandTotalAmount>'
        "</SpecifiedTradeSettlementHeaderMonetarySummation>"
        "</ApplicableHeaderTradeSettlement></SupplyChainTradeTransaction>"
        "</CrossIndustryInvoice>"
    )
    d = lesen(p)
    assert d["syntax"] == "cii"
    assert d["nummer"] == "C-1"
    assert d["betrag"] == 23.8


def test_doctype_wird_abgelehnt(repo):
    p = repo / "boese.xml"
    p.write_text('<!DOCTYPE x [<!ENTITY a "x">]><Invoice>&a;</Invoice>')
    with pytest.raises(ValueError):
        lesen(p)


def test_sicht_pdf_hat_hash_hinweis(repo):
    xml = repo / "x.xml"
    xml.write_text("<Invoice/>")
    ziel = repo / "sicht.pdf"
    sicht_pdf({"nummer": "1", "positionen": []}, xml, ziel)
    text = subprocess.run(["pdftotext", str(ziel), "-"], capture_output=True, text=True).stdout
    assert ziel.exists()
    assert xml.name in text
    assert "SHA-256" in text
