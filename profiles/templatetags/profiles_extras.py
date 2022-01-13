from django import template
from django.utils.safestring import mark_safe
from django import template
from django.template import Template, Context

register = template.Library()


@register.filter
def parenthesize(text: any) -> str:
    """If a value contains anything, wrap it in with parenthesise, and prepend with one space. If not, just pass it on.
    """
    if text:
        template = Template(f"&nbsp;({text})")
        return template.render(Context({'text': text}))
    else:
        return text


@register.simple_tag(takes_context=True)
def link_to_others(context, other_person) -> str:
    """
    If it's me, don't make my name a link.
    If it's a non-officer, and I'm an admin, link to the person edit page
    If it's a non-officer, and I'm a staff member, don't make it a link
    Context should be the request context as populated by OfficerDetailView()
    """
    if other_person.pk == context.get('object').pk:
        template = Template("<span class='associate-self'>{{ person.name }}</span>")
        return template.render(context)
    elif other_person.is_law_enforcement is False and context.get('is_admin'):
        template = Template(f"<a href='{ other_person.get_edit_url }'>{ other_person.name }</a>")
        return template.render(context)
    elif other_person.is_law_enforcement is False and context.get('is_admin') is False:
        template = Template(f"{other_person.name}")
        return template.render(context)
    else:
        template = Template(f"<a href='{ other_person.get_profile_url }' class='associate-link'>{ other_person.name }</a>")
        return template.render(context)


@register.filter
def format_identifiers(identifiers: list) -> str:
    """Returns a concatenated string of the identifier values from a list of identifier objects
    """
    if identifiers:
        identifiers_values = []
        for identifier in identifiers:
            identifiers_values.append(identifier.identifier)
        return f"({', '.join(identifiers_values)})"
    else:
        return ''


@register.filter
def get_value(dictionary, key):
    """ Retrieve a value from a dictionary given a particular key.

    :param dictionary: Dictionary from which to retrieve value.
    :param key: Key for which to retrieve value.
    :return: Value retrieved from the dictionary with the key.
    """
    return dictionary.get(key)


@register.filter
def get_item(list_obj, index):
    """ Retrieve an item from a list given a particular index.

    :param list_obj: List from which to retrieve item.
    :param index: Index for which to retrieve item.
    :return: Item retrieved from the list with the index.
    """
    return list_obj[index]

@register.filter
def table_cell(input_value):
    if input_value:
        return input_value
    else:
        return mark_safe("<span class='empty-table-field'>&mdash;</span>")

@register.filter
def table_cell_currency(input_value):
    if input_value:
        return f"${input_value}"
    else:
        return mark_safe("<span class='empty-table-field'>&mdash;</span>")
