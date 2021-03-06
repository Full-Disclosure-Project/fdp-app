# Generated by Django 3.1.3 on 2021-02-11 08:25

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import fdpuser.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cspreports', '0004_cspreport_user_agent'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='FdpUser',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('email', models.EmailField(help_text='Email address used as the username to uniquely identify the user', max_length=254, unique=True, verbose_name='Email address')),
                ('is_host', models.BooleanField(default=False, help_text='Select if the user belongs to the host organization', verbose_name='Belongs to host organization')),
                ('is_administrator', models.BooleanField(default=False, help_text='Select if the user is an Administrator', verbose_name='Is Administrator')),
                ('is_superuser', models.BooleanField(default=False, help_text='Select if the user is a Super User', verbose_name='Is Super User')),
                ('is_active', models.BooleanField(default=True, help_text='If not selected, the user is deactivated and cannot log in, regardless of their user role. Deactivate users instead of deleting them.', verbose_name='Is Active')),
                ('only_external_auth', models.BooleanField(default=False, help_text='If selected, the user can only be authenticated through an external authentication mechanism, such as Azure Active Directory.', verbose_name='Only Externally Authenticated')),
            ],
            options={
                'verbose_name': 'FDP User',
                'db_table': 'fdp_fdp_user',
                'ordering': ['email'],
            },
            managers=[
                ('objects', fdpuser.models.FdpUserManager()),
            ],
        ),
        migrations.CreateModel(
            name='FdpOrganization',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_archived', models.BooleanField(default=False, help_text='Select if record is archived', verbose_name='Is archived')),
                ('name', models.CharField(help_text='Name of organization using FDP system', max_length=254, unique=True, verbose_name='name')),
            ],
            options={
                'verbose_name': 'FDP Organization',
                'db_table': 'fdp_fdp_organization',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='FdpCSPReport',
            fields=[
            ],
            options={
                'verbose_name': 'CSP Report',
                'verbose_name_plural': 'CSP Reports',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('cspreports.cspreport',),
        ),
        migrations.CreateModel(
            name='PasswordReset',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True, help_text='Automatically added timestamp for when the password was reset', verbose_name='timestamp')),
                ('ip_address', models.CharField(blank=True, help_text='IP address of client from which password reset was initiated', max_length=50, validators=[django.core.validators.validate_ipv46_address], verbose_name='IP address')),
                ('fdp_user', models.ForeignKey(help_text='FDP user whose password was reset', on_delete=django.db.models.deletion.CASCADE, related_name='password_resets', related_query_name='password_reset', to=settings.AUTH_USER_MODEL, verbose_name='FDP user')),
            ],
            options={
                'verbose_name': 'Password reset',
                'db_table': 'fdp_password_reset',
                'ordering': ['timestamp'],
            },
        ),
        migrations.AddField(
            model_name='fdpuser',
            name='fdp_organization',
            field=models.ForeignKey(blank=True, help_text='Organization to which user belongs. If user belongs to the host organization, this can be left blank.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='fdp_users', related_query_name='fdp_user', to='fdpuser.fdporganization', verbose_name='organization'),
        ),
        migrations.AddField(
            model_name='fdpuser',
            name='groups',
            field=models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.Group', verbose_name='groups'),
        ),
        migrations.AddField(
            model_name='fdpuser',
            name='user_permissions',
            field=models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.Permission', verbose_name='user permissions'),
        ),
    ]
