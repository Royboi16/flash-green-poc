from app.storage import (
    init_db,
    save_trade,
    get_trades,
    record_loan_drawdown,
    record_loan_repayment,
    get_loan_events,
    get_loan_balances,
)


def test_save_and_load(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)

    trade = save_trade(qty_mwh=1.5, spot_price=-5.0, fut_price=65.0, profit=100.0)
    recs = get_trades(limit=10)
    assert len(recs) == 1
    assert recs[0].profit == 100.0
    assert trade.id == recs[0].id


def test_loan_events_and_balances(tmp_path):
    db = tmp_path / "loan.db"
    init_db(db)

    record_loan_drawdown(asset="gbp", amount=50.0, reference="ref-1")
    record_loan_repayment(asset="gbp", amount=50.0, reference="ref-1")

    events = get_loan_events(limit=10)
    assert len(events) == 2
    balances = get_loan_balances()
    assert balances[0].asset == "gbp"
    assert balances[0].outstanding == 0
