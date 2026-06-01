"""
Тесты CRM Engine (Part 9)
==============================
Interaction, CRMContact, Deal, SupplierScore, InteractionLog,
DealPipeline, ContactManager, CRMEngine.
~65 тестов.
"""

from datetime import datetime, timedelta

from pds_ultimate.core.crm_engine import (
    ContactManager,
    ContactType,
    CRMContact,
    CRMEngine,
    Deal,
    DealPipeline,
    DealPriority,
    DealStage,
    Interaction,
    InteractionLog,
    InteractionType,
    SupplierScore,
    crm_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnums:
    """Enum smoke tests."""

    def test_contact_type(self):
        assert ContactType.CLIENT.value == "client"
        assert ContactType.SUPPLIER.value == "supplier"
        assert ContactType.PARTNER.value == "partner"

    def test_interaction_type(self):
        assert InteractionType.CALL.value == "call"
        assert InteractionType.MESSAGE.value == "message"
        assert InteractionType.MEETING.value == "meeting"
        assert InteractionType.EMAIL.value == "email"

    def test_deal_stage(self):
        assert DealStage.LEAD.value == "lead"
        assert DealStage.QUALIFIED.value == "qualified"
        assert DealStage.PROPOSAL.value == "proposal"
        assert DealStage.NEGOTIATION.value == "negotiation"
        assert DealStage.CLOSED_WON.value == "closed_won"
        assert DealStage.CLOSED_LOST.value == "closed_lost"

    def test_deal_priority(self):
        assert DealPriority.LOW.value == "low"
        assert DealPriority.MEDIUM.value == "medium"
        assert DealPriority.HIGH.value == "high"
        assert DealPriority.CRITICAL.value == "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# Interaction
# ═══════════════════════════════════════════════════════════════════════════════


class TestInteraction:
    """Interaction — запись взаимодействия."""

    def test_create(self):
        i = Interaction(
            contact_id="c1",
            interaction_type=InteractionType.CALL,
            summary="Позвонил",
        )
        assert i.contact_id == "c1"
        assert i.interaction_type == InteractionType.CALL
        assert i.id

    def test_to_dict(self):
        i = Interaction(
            contact_id="c1",
            interaction_type=InteractionType.MESSAGE,
            summary="Написал",
        )
        d = i.to_dict()
        assert d["contact_id"] == "c1"
        assert d["type"] == "message"
        assert "id" in d


# ═══════════════════════════════════════════════════════════════════════════════
# CRMContact
# ═══════════════════════════════════════════════════════════════════════════════


class TestCRMContact:
    """CRMContact — контакт CRM."""

    def test_create(self):
        c = CRMContact(name="Иван", contact_type=ContactType.CLIENT)
        assert c.name == "Иван"
        assert c.id
        assert c.rating == 0.0

    def test_star_rating_zero(self):
        c = CRMContact(name="X")
        assert "☆" in c.star_rating

    def test_star_rating_max(self):
        c = CRMContact(name="X", rating=5.0)
        sr = c.star_rating
        assert "★" in sr

    def test_star_rating_half(self):
        c = CRMContact(name="X", rating=2.5)
        sr = c.star_rating
        assert "½" in sr or "★" in sr

    def test_update_rating(self):
        c = CRMContact(name="X", rating=3.0)
        c.update_rating(5.0)
        assert c.rating > 3.0

    def test_update_rating_first(self):
        c = CRMContact(name="X", rating=0.0)
        c.update_rating(4.0)
        assert c.rating > 0.0

    def test_days_since_contact(self):
        c = CRMContact(name="X")
        c.last_interaction = datetime.utcnow() - timedelta(days=5)
        assert c.days_since_contact >= 5

    def test_days_since_contact_none(self):
        c = CRMContact(name="X")
        c.last_interaction = None
        assert c.days_since_contact == -1

    def test_format_card(self):
        c = CRMContact(
            name="Тестовый", contact_type=ContactType.SUPPLIER,
            rating=4.0,
        )
        card = c.format_card()
        assert "Тестовый" in card

    def test_to_dict(self):
        c = CRMContact(name="Dict", rating=3.5)
        d = c.to_dict()
        assert d["name"] == "Dict"
        assert d["rating"] == 3.5
        assert "id" in d


# ═══════════════════════════════════════════════════════════════════════════════
# Deal
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeal:
    """Deal — сделка."""

    def test_create(self):
        d = Deal(title="Поставка 100 ед.")
        assert d.title == "Поставка 100 ед."
        assert d.stage == DealStage.LEAD
        assert d.id

    def test_advance_stage(self):
        d = Deal(title="Test")
        d.advance_stage()
        assert d.stage == DealStage.QUALIFIED
        d.advance_stage()
        assert d.stage == DealStage.PROPOSAL
        d.advance_stage()
        assert d.stage == DealStage.NEGOTIATION

    def test_advance_beyond_negotiation(self):
        d = Deal(title="X", stage=DealStage.NEGOTIATION)
        d.advance_stage()
        # Should stay at negotiation
        assert d.stage == DealStage.NEGOTIATION

    def test_close_won(self):
        d = Deal(title="Win")
        d.close_won()
        assert d.stage == DealStage.CLOSED_WON

    def test_close_lost(self):
        d = Deal(title="Lose")
        d.close_lost()
        assert d.stage == DealStage.CLOSED_LOST

    def test_amount(self):
        d = Deal(title="D1", amount=5000)
        assert d.amount == 5000

    def test_to_dict(self):
        d = Deal(title="D1", amount=5000)
        dd = d.to_dict()
        assert dd["title"] == "D1"
        assert dd["amount"] == 5000
        assert "stage" in dd


# ═══════════════════════════════════════════════════════════════════════════════
# SupplierScore
# ═══════════════════════════════════════════════════════════════════════════════


class TestSupplierScore:
    """SupplierScore — оценка поставщика."""

    def test_create(self):
        ss = SupplierScore(contact_id="s1")
        assert ss.contact_id == "s1"

    def test_overall_score_default(self):
        ss = SupplierScore(contact_id="s1")
        # All defaults are 3.0 → overall = 3.0
        assert ss.overall_score == 3.0

    def test_overall_score_with_values(self):
        ss = SupplierScore(
            contact_id="s1",
            reliability=4.0, quality=5.0,
            pricing=3.0, communication=4.0,
            delivery_speed=5.0,
        )
        score = ss.overall_score
        assert 3.0 < score < 5.0

    def test_weighted_formula_all_max(self):
        ss = SupplierScore(
            contact_id="s1",
            reliability=5.0, quality=5.0,
            pricing=5.0, communication=5.0,
            delivery_speed=5.0,
        )
        assert ss.overall_score == 5.0

    def test_update_category(self):
        ss = SupplierScore(contact_id="s1")
        ss.update_category("reliability", 5.0)
        assert ss.reliability != 3.0  # Should have changed via weighted avg

    def test_to_dict(self):
        ss = SupplierScore(contact_id="s1")
        d = ss.to_dict()
        assert d["contact_id"] == "s1"
        assert "overall" in d


# ═══════════════════════════════════════════════════════════════════════════════
# InteractionLog
# ═══════════════════════════════════════════════════════════════════════════════


class TestInteractionLog:
    """InteractionLog — журнал взаимодействий."""

    def test_add_and_get_history(self):
        log = InteractionLog()
        log.add("c1", InteractionType.CALL, "Тест")
        entries = log.get_history("c1")
        assert len(entries) == 1

    def test_get_empty(self):
        log = InteractionLog()
        assert log.get_history("c1") == []

    def test_total_interactions(self):
        log = InteractionLog()
        log.add("c1", InteractionType.CALL, "call 1")
        log.add("c1", InteractionType.EMAIL, "email 1")
        log.add("c2", InteractionType.MEETING, "meeting 1")
        assert log.total_interactions == 3

    def test_add_with_follow_up(self):
        log = InteractionLog()
        interaction = log.add("c1", InteractionType.CALL,
                              "call", follow_up_days=7)
        assert interaction.follow_up_date is not None


# ═══════════════════════════════════════════════════════════════════════════════
# DealPipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestDealPipeline:
    """DealPipeline — воронка сделок."""

    def test_create_deal(self):
        p = DealPipeline()
        d = p.create_deal(title="Deal 1", amount=1000)
        assert d.title == "Deal 1"
        assert len(p.find_deals()) == 1

    def test_find_by_stage(self):
        p = DealPipeline()
        p.create_deal(title="Lead1")
        p.create_deal(title="Lead2")
        d3 = p.create_deal(title="Qual1")
        d3.advance_stage()
        leads = p.find_deals(stage=DealStage.LEAD)
        assert len(leads) == 2

    def test_get_pipeline_value(self):
        p = DealPipeline()
        p.create_deal(title="D1", amount=1000)
        p.create_deal(title="D2", amount=2000)
        assert p.get_pipeline_value() == 3000

    def test_get_weighted_pipeline(self):
        p = DealPipeline()
        p.create_deal(title="D1", amount=1000)
        weighted = p.get_weighted_pipeline()
        assert isinstance(weighted, (int, float))

    def test_format_pipeline(self):
        p = DealPipeline()
        p.create_deal(title="FormatDeal", amount=500)
        text = p.format_pipeline()
        assert isinstance(text, str)

    def test_get_stats(self):
        p = DealPipeline()
        p.create_deal(title="S1", amount=100)
        stats = p.get_stats()
        assert stats["total"] == 1
        assert "pipeline_value" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# ContactManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestContactManager:
    """ContactManager — управление контактами."""

    def test_create_contact(self):
        cm = ContactManager()
        c = cm.create_contact(name="Тест", contact_type="client")
        assert c.name == "Тест"

    def test_get_contact(self):
        cm = ContactManager()
        c = cm.create_contact(name="Get")
        found = cm.get_contact(c.id)
        assert found is c

    def test_find_by_name(self):
        cm = ContactManager()
        cm.create_contact(name="FindMe")
        found = cm.find_by_name("FindMe")
        assert len(found) == 1
        assert found[0].name == "FindMe"

    def test_find_by_name_partial(self):
        cm = ContactManager()
        cm.create_contact(name="Полное Имя Контакта")
        found = cm.find_by_name("Полное")
        assert len(found) == 1

    def test_search_by_query(self):
        cm = ContactManager()
        cm.create_contact(name="Альберт Поставщик", contact_type="supplier")
        cm.create_contact(name="Борис Покупатель", contact_type="client")
        results = cm.search(query="Альберт")
        assert len(results) == 1
        assert results[0].name == "Альберт Поставщик"

    def test_search_by_type(self):
        cm = ContactManager()
        cm.create_contact(name="S1", contact_type="supplier")
        cm.create_contact(name="C1", contact_type="client")
        results = cm.search(contact_type=ContactType.SUPPLIER)
        assert len(results) == 1

    def test_search_by_rating(self):
        cm = ContactManager()
        cm.create_contact(name="Good", rating=4.5)
        cm.create_contact(name="Bad", rating=2.0)
        results = cm.search(min_rating=4.0)
        assert len(results) == 1
        assert results[0].name == "Good"

    def test_get_stats(self):
        cm = ContactManager()
        cm.create_contact(name="A")
        cm.create_contact(name="B")
        stats = cm.get_stats()
        assert stats["total"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# CRMEngine (facade)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCRMEngine:
    """CRMEngine — главный фасад."""

    def test_add_contact(self):
        crm = CRMEngine()
        c = crm.add_contact(name="Тест", contact_type="client")
        assert c.name == "Тест"

    def test_rate_contact(self):
        crm = CRMEngine()
        crm.add_contact(name="Rated")
        c = crm.rate_contact("Rated", 4.5, "Отличный")
        assert c is not None
        assert c.rating > 0

    def test_rate_contact_not_found(self):
        crm = CRMEngine()
        result = crm.rate_contact("NoSuch", 3.0)
        assert result is None

    def test_log_interaction(self):
        crm = CRMEngine()
        crm.add_contact(name="Inter")
        i = crm.log_interaction("Inter", "call", "Звонок")
        assert i is not None

    def test_search_contacts(self):
        crm = CRMEngine()
        crm.add_contact(name="Ахмед Поставщик", contact_type="supplier")
        crm.add_contact(name="Олег Покупатель", contact_type="client")
        results = crm.search_contacts(query="Ахмед")
        assert len(results) == 1

    def test_search_contacts_by_type(self):
        crm = CRMEngine()
        crm.add_contact(name="S1", contact_type="supplier")
        crm.add_contact(name="C1", contact_type="client")
        results = crm.search_contacts(contact_type="supplier")
        assert len(results) == 1

    def test_rate_supplier(self):
        crm = CRMEngine()
        crm.add_contact(name="Supp", contact_type="supplier")
        sc = crm.rate_supplier("Supp", "reliability", 4.5)
        assert sc is not None
        # update_category uses weighted average: 3.0*0.7 + 4.5*0.3 = 3.45
        assert sc.reliability != 3.0

    def test_rate_supplier_not_found(self):
        crm = CRMEngine()
        result = crm.rate_supplier("Nobody", "quality", 3.0)
        assert result is None

    def test_create_deal(self):
        crm = CRMEngine()
        d = crm.create_deal(title="Новый заказ", amount=5000)
        assert d.title == "Новый заказ"
        assert d.amount == 5000

    def test_get_stats(self):
        crm = CRMEngine()
        crm.add_contact(name="A")
        crm.create_deal(title="D1")
        stats = crm.get_stats()
        assert stats["contacts"]["total"] == 1
        assert stats["pipeline"]["total"] == 1
        assert "interactions" in stats

    def test_get_stats_empty(self):
        crm = CRMEngine()
        stats = crm.get_stats()
        assert stats["contacts"]["total"] == 0

    def test_global_instance(self):
        assert crm_engine is not None
        assert isinstance(crm_engine, CRMEngine)
