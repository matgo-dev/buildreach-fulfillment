from app.db.models.spu import Spu
from app.db.models.sku import Sku


def test_spu_has_code_and_softdelete_columns():
    cols = Spu.__table__.columns.keys()
    assert "spu_code" in cols
    assert "deleted_at" in cols


def test_sku_has_softdelete_column():
    assert "deleted_at" in Sku.__table__.columns.keys()
    assert Sku.__table__.columns["spu_id"] is not None
