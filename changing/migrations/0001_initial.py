# Generated by Django 3.1.3 on 2021-02-11 08:25

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ContentChangingSearch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_search_criteria', models.CharField(blank=True, help_text='Original search text as it was entered by the user', max_length=254, verbose_name='original search text')),
                ('unique_table_suffix', models.CharField(blank=True, help_text='Unique suffix used for temporary tables for this particular user and search context', max_length=254, verbose_name='unique table suffix')),
            ],
            options={
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='GroupingChangingSearch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_search_criteria', models.CharField(blank=True, help_text='Original search text as it was entered by the user', max_length=254, verbose_name='original search text')),
                ('unique_table_suffix', models.CharField(blank=True, help_text='Unique suffix used for temporary tables for this particular user and search context', max_length=254, verbose_name='unique table suffix')),
            ],
            options={
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='IncidentChangingSearch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_search_criteria', models.CharField(blank=True, help_text='Original search text as it was entered by the user', max_length=254, verbose_name='original search text')),
                ('unique_table_suffix', models.CharField(blank=True, help_text='Unique suffix used for temporary tables for this particular user and search context', max_length=254, verbose_name='unique table suffix')),
            ],
            options={
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PersonChangingSearch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_search_criteria', models.CharField(blank=True, help_text='Original search text as it was entered by the user', max_length=254, verbose_name='original search text')),
                ('unique_table_suffix', models.CharField(blank=True, help_text='Unique suffix used for temporary tables for this particular user and search context', max_length=254, verbose_name='unique table suffix')),
            ],
            options={
                'managed': False,
            },
        ),
    ]
