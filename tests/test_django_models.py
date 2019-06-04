# -- encoding: UTF-8 --

from django.core.exceptions import ValidationError
from django.db import connection

import pytest

from .enums import Color, IntegerEnum, LabeledEnum, StateFlow, StateFlowAnyFirst, SubIntegerEnum, Taste, ZeroEnum
from .models import MyModel


@pytest.mark.django_db
def test_field_value():
    m = MyModel(color=Color.RED)
    m.save()
    assert m.color == Color.RED

    m = MyModel.objects.filter(color=Color.RED)[0]
    assert m.color == Color.RED

    # Passing the value should work the same way as passing the enum
    assert Color.RED.value == 'r'
    m = MyModel.objects.filter(color='r')[0]
    assert m.color == Color.RED

    with pytest.raises(ValueError):
        MyModel.objects.filter(color='xx')[0]


@pytest.mark.django_db
def test_db_value():
    m = MyModel(color=Color.RED)
    m.save()
    cursor = connection.cursor()
    cursor.execute('SELECT color FROM %s WHERE id = %%s' % MyModel._meta.db_table, [m.pk])
    assert cursor.fetchone()[0] == Color.RED.value


@pytest.mark.django_db
def test_enum_int_field_validators():
    if not hasattr(connection.ops, 'integer_field_range'):
        return pytest.skip('Needs connection.ops.integer_field_range')

    # Make sure that integer_field_range returns a range.
    # This is needed to make SQLite emulate a "real" db
    orig_method = connection.ops.integer_field_range
    connection.ops.integer_field_range = (lambda *args: (-100, 100))

    m = MyModel(color=Color.RED)

    # Uncache validators property of taste_int
    for f in m._meta.fields:
        if f.name == 'taste_int':
            if 'validators' in f.__dict__:
                del f.__dict__['validators']

    # Run the validators
    m.full_clean()

    # Revert integer_field_range method
    connection.ops.integer_field_range = orig_method


@pytest.mark.django_db
def test_zero_enum_loads():
    # Verifies that we can save and load enums with the value of 0 (zero).
    m = MyModel(zero_field=ZeroEnum.ZERO,
                color=Color.GREEN)
    m.save()
    assert m.zero_field == ZeroEnum.ZERO

    m = MyModel.objects.get(id=m.id)
    assert m.zero_field == ZeroEnum.ZERO


@pytest.mark.django_db
def test_int_enum():
    m = MyModel(int_enum=IntegerEnum.A, color=Color.RED)
    m.save()

    m = MyModel.objects.get(id=m.id)
    assert m.int_enum == IntegerEnum.A
    assert isinstance(m.int_enum, IntegerEnum)


def test_serialization():
    from django.core.serializers.python import Serializer as PythonSerializer
    m = MyModel(color=Color.RED, taste=Taste.SALTY)
    ser = PythonSerializer()
    ser.serialize([m])
    fields = ser.getvalue()[0]["fields"]
    assert fields["color"] == m.color.value
    assert fields["taste"] == m.taste.value


@pytest.mark.django_db
def test_nonunique_label():
    obj = MyModel.objects.create(
        color=Color.BLUE,
        labeled_enum=LabeledEnum.FOOBAR
    )
    assert obj.labeled_enum is LabeledEnum.FOOBAR

    obj = MyModel.objects.get(pk=obj.pk)
    assert obj.labeled_enum is LabeledEnum.FOOBAR


def test_sub_enum_field():
    with pytest.raises(ValidationError):
        MyModel(color=Color.RED, int_enum=IntegerEnum.A, sub_int_enum=SubIntegerEnum.D).full_clean()
    MyModel(color=Color.RED, int_enum=IntegerEnum.C).full_clean()
    MyModel(color=Color.RED, int_enum=IntegerEnum.A, sub_int_enum=SubIntegerEnum.C).full_clean()
    MyModel(color=Color.RED, int_enum=IntegerEnum.B, sub_int_enum=SubIntegerEnum.C).full_clean()
    MyModel(color=Color.RED, int_enum=IntegerEnum.B, sub_int_enum=SubIntegerEnum.D).full_clean()
    MyModel(color=Color.RED).full_clean()


@pytest.mark.django_db
def test_next_states_enum_field():
    model = MyModel.objects.create(color=Color.RED)

    with pytest.raises(ValidationError):
        # invalid transition from START to END
        model.any_first_state = StateFlowAnyFirst.END
        model.full_clean()

    model.any_first_state = StateFlowAnyFirst.PROCESSING
    model.full_clean()

    # does not update initial value of any_first_state field
    model.save(update_fields=['color'])
    with pytest.raises(ValidationError):
        # invalid transition from START to END
        model.any_first_state = StateFlowAnyFirst.END
        model.full_clean()

    # initial values of fields during save are updated
    model.any_first_state = StateFlowAnyFirst.PROCESSING
    model.save()
    model.any_first_state = StateFlowAnyFirst.END
    model.full_clean()

    # field values are updated correctly from model loaded from db
    model_from_db = MyModel.objects.get(pk=model.pk)
    model_from_db.any_first_state = StateFlowAnyFirst.END
    model_from_db.full_clean()

    with pytest.raises(ValidationError):
        # invalid transition from PROCESSING to START
        model_from_db.any_first_state = StateFlowAnyFirst.START
        model_from_db.full_clean()

    MyModel(color=Color.RED, any_first_state=StateFlowAnyFirst.END).full_clean()


def test_initial_enum_field():
    MyModel(color=Color.RED, state=StateFlow.START).full_clean()

    with pytest.raises(ValidationError):
        # END is not initial state
        MyModel(color=Color.RED, state=StateFlow.END).full_clean()
