import pytest

from src.app.services.chat_research_entry import literal_research_subject_matches


@pytest.mark.parametrize('query', [
    'Search online for the official FreeCAD 1.0 requirements.',
    'Check the official FreeCAD 1.0 requirements',
    'Look up requirements for FreeCAD 1.0.',
    'Find FreeCAD requirements',
])
def test_literal_same_subject_requirements_can_be_associated(query):
    assert literal_research_subject_matches(query, 'I need 30 laptops for FreeCAD 1.0 mechanical design.')


@pytest.mark.parametrize('query', [
    'Search online for the official FreeCAD 2.0 requirements.',
    'Search online for the official AnotherCAD 1.0 requirements.',
    'Check the official current software requirements.',
    'Instead search online for the official FreeCAD 1.0 requirements.',
    'Search online for the official FreeCAD 1.0 requirements and Blender requirements.',
    'Search online for the official 30 requirements.',
    'Search online for the official CAD requirements.',
])
def test_different_version_topic_generic_or_nonliteral_subject_is_not_associated(query):
    assert not literal_research_subject_matches(query, 'I need 30 laptops for FreeCAD 1.0 mechanical design.')
