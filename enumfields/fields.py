from enum import Enum

import django
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.fields import BLANK_CHOICE_DASH
from django.utils.functional import cached_property
from django.utils.module_loading import import_string
from django.utils.translation import ugettext

from .forms import EnumChoiceField


class CastOnAssignDescriptor:
    """
    A property descriptor which ensures that `field.to_python()` is called on _every_ assignment to the field.

    This used to be provided by the `django.db.models.subclassing.Creator` class, which in turn
    was used by the deprecated-in-Django-1.10 `SubfieldBase` class, hence the reimplementation here.
    """

    def __init__(self, field):
        self.field = field

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return obj.__dict__[self.field.name]

    def __set__(self, obj, value):
        obj.__dict__[self.field.name] = self.field.to_python(value)


class EnumFieldMixin:

    def __init__(self, enum, **options):
        if isinstance(enum, str):
            self.enum = import_string(enum)
        else:
            self.enum = enum

        if 'choices' not in options:
            options['choices'] = [  # choices for the TypedChoiceField
                (i, getattr(i, 'label', i.name))
                for i in self.enum
            ]

        super(EnumFieldMixin, self).__init__(**options)

    def contribute_to_class(self, cls, name):
        super(EnumFieldMixin, self).contribute_to_class(cls, name)
        setattr(cls, name, CastOnAssignDescriptor(self))

    def to_python(self, value):
        if value is None or value == '':
            return None
        if isinstance(value, self.enum):
            return value
        for m in self.enum:
            if value == m:
                return m
            if value == m.value or str(value) == str(m.value) or str(value) == str(m):
                return m
        raise ValidationError('%s is not a valid value for enum %s' % (value, self.enum), code='invalid_enum_value')

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, self.enum):  # Already the correct type -- fast path
            return value.value
        return self.enum(value).value

    def from_db_value(self, value, expression, connection, *args):
        return self.to_python(value)

    def value_to_string(self, obj):
        """
        This method is needed to support proper serialization. While its name is value_to_string()
        the real meaning of the method is to convert the value to some serializable format.
        Since most of the enum values are strings or integers we WILL NOT convert it to string
        to enable integers to be serialized natively.
        """
        if django.VERSION >= (2, 0):
            value = self.value_from_object(obj)
        else:
            value = self._get_val_from_obj(obj)
        return value.value if value else None

    def get_default(self):
        if self.has_default():
            if self.default is None:
                return None

            if isinstance(self.default, Enum):
                return self.default

            return self.enum(self.default)

        return super(EnumFieldMixin, self).get_default()

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['enum'] = self.enum
        kwargs.pop('choices', None)
        if 'default' in kwargs:
            if hasattr(kwargs['default'], 'value'):
                kwargs['default'] = kwargs['default'].value

        return name, path, args, kwargs

    def get_choices(self, include_blank=True, blank_choice=BLANK_CHOICE_DASH):
        # Force enum fields' options to use the `value` of the enumeration
        # member as the `value` of SelectFields and similar.
        return [
            (i.value if isinstance(i, Enum) else i, display)
            for (i, display)
            in super(EnumFieldMixin, self).get_choices(include_blank, blank_choice)
        ]

    def formfield(self, form_class=None, choices_form_class=None, **kwargs):
        if not choices_form_class:
            choices_form_class = EnumChoiceField

        return super(EnumFieldMixin, self).formfield(
            form_class=form_class,
            choices_form_class=choices_form_class,
            **kwargs
        )


class EnumField(EnumFieldMixin, models.CharField):

    def __init__(self, enum, **kwargs):
        kwargs.setdefault('max_length', 10)
        super(EnumField, self).__init__(enum, **kwargs)
        self.validators = []


class NumEnumField(EnumFieldMixin, models.IntegerField):

    @cached_property
    def validators(self):
        # Skip IntegerField validators, since they will fail with
        #   TypeError: unorderable types: TheEnum() < int()
        # when used database reports min_value or max_value from
        # connection.ops.integer_field_range method.
        return super(models.IntegerField, self).validators

    def get_prep_value(self, value):
        if value is None:
            return None

        if isinstance(value, Enum):
            return value.value

        try:
            return int(value)
        except ValueError:
            return self.to_python(value).value


class EnumSubFieldMixin:

    def __init__(self, parent_field_name, enum, **options):
        self.parent_field_name = parent_field_name
        super().__init__(enum, **options)

    def _get_supvalue(self, model_instance):
        return getattr(model_instance, self.parent_field_name)

    def _get_all_parent_values(self):
        parents = set()
        for choice in self.enum:
            parents |= set(choice.parents)
        return parents

    def _get_all_parent_choices(self, supvalue):
        return {
            choice for choice in self.enum if supvalue in choice.parents
        }

    def clean(self, value, model_instance):
        if self._get_all_parent_choices(self._get_supvalue(model_instance)):
            return super().clean(value, model_instance)
        else:
            return None

    def _raise_error_if_value_should_be_empty(self, value, supvalue):
        if supvalue not in self._get_all_parent_values() and value is not None:
            raise ValidationError(ugettext('Value must be empty'))

    def _raise_error_if_value_not_allowed(self, value, supvalue):
        allowed_values = self._get_all_parent_choices(supvalue)
        if allowed_values and value not in allowed_values:
            raise ValidationError(ugettext('Allowed choices are {}.').format(
                ', '.join(('{} ({})'.format(*(val.label, val)) for val in allowed_values))
            ))

    def validate(self, value, model_instance):
        self._raise_error_if_value_should_be_empty(value, self._get_supvalue(model_instance))
        self._raise_error_if_value_not_allowed(value, self._get_supvalue(model_instance))

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['parent_field_name'] = self.parent_field_name
        return name, path, args, kwargs


class EnumSubField(EnumSubFieldMixin, EnumField):
    pass


class NumEnumSubField(EnumSubFieldMixin, NumEnumField):
    pass
