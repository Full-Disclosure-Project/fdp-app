import os
from datetime import datetime
from time import sleep

from django.urls import reverse
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from .models import ImportBatch
from .narwhal import do_import_from_disk, ImportReport
from django.test import TestCase
from django.core.management import call_command
from io import StringIO
import tempfile
import csv
from uuid import uuid4
from django.test import TestCase, override_settings
from core.models import Person
from functional_tests.common import FunctionalTestCase, SeleniumFunctionalTestCase, wait
from inheritable.tests import local_test_settings_required
from unittest import expectedFailure, skip
from selenium.webdriver.support.ui import Select

import pdb


def wait_until_dry_run_is_done():
    for _ in range(60):
        if ImportBatch.objects.last().dry_run_completed:
            break
        else:
            sleep(1)


def wait_until_import_is_done():
    for _ in range(60):
        if ImportBatch.objects.last().completed:
            break
        else:
            sleep(1)


class TestWebUI(SeleniumFunctionalTestCase):
    def test_import_batch_page_success_scenario(self):
        # GIVEN an import has been run
        with tempfile.NamedTemporaryFile(mode='w') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(42):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'checked'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!
            report = do_import_from_disk('Person', csv_fd.name)

            # WHEN I go to the batch history page
            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')

            # Then I should see the basic data points
            self.assertIn('Person', self.browser.page_source)
            self.assertIn('42', self.browser.page_source)
            self.assertIn(os.path.basename(csv_fd.name), self.browser.page_source)

    def test_import_batch_page_errors_pagination_first_page(self):
        # GIVEN an import has been run with validation errors
        with tempfile.NamedTemporaryFile(mode='w') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(3):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'BREAK'  # <-- bad value
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!
            do_import_from_disk('Person', csv_fd.name)

            # WHEN I go to the batch history page
            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')

            # THEN I should see a listing showing the error rows of the import
            self.assertEqual(
                3,
                self.browser.page_source.count("Enter a valid boolean value")
            )

    def test_batch_listing(self):
        # GIVEN an import has been run
        with tempfile.NamedTemporaryFile(mode='w') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(42):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'checked'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!
            report = do_import_from_disk('Person', csv_fd.name)

            # WHEN I go to the batch listing page
            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + f'/changing/importer')

            # Then I should see the batch in the listing
            self.assertIn('Person', self.browser.page_source)
            self.assertIn('42', self.browser.page_source)
            self.assertIn(os.path.basename(csv_fd.name), self.browser.page_source)

    def test_batch_listing_links_to_detail_page(self):
        # GIVEN an import has been run
        with tempfile.NamedTemporaryFile(mode='w') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(42):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'checked'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!
            report = do_import_from_disk('Person', csv_fd.name)

            # WHEN I click one of the batches on the batch listing page
            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + f'/changing/importer')
            self.browser.find_element(By.CSS_SELECTOR, '.row-1 a').click()

            # Then I should see the batch detail page
            self.assertIn('Person', self.browser.page_source)
            self.assertIn('42', self.browser.page_source)
            self.assertIn(os.path.basename(csv_fd.name), self.browser.page_source)

    def test_validation_step_column_mapping_errors(self):
        # Given I upload an import sheet with a nonsense column that doesn't match any of the columns of the resource
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'supercalifragilisticexpialidocious'])
            csv_writer.writeheader()
            for i in range(42):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['supercalifragilisticexpialidocious'] = 'yes'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + f'/changing/importer/batch/new')
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('Person')

            # And I'm on the validation step of running an import
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

        # When I click Validate Batch
        wait(self.browser.find_element_by_css_selector, 'input[value="Validate Batch"]') \
            .submit()

        # Then I should see an error report that warns me that it's an un-expected field name
        general_errors_div = wait(self.browser.find_element_by_css_selector, 'div.general-errors')
        self.assertIn(
            "ERROR: 'supercalifragilisticexpialidocious' not a valid column name for Person imports",
            general_errors_div.text
        )
        self.assertNotIn(
            'there were no errors',
            self.browser.page_source
        )


class TestImportWorkflowPageElementsExist(SeleniumFunctionalTestCase):

    def test_validate_pre_validate(self):
        """Test that the CSV Preview, Info Card, and Status Guide elements are displayed on the batch detail page
        when in the pre-validate state"""
        # Given I've set up a batch from the Import batch setup page
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'mineralogize'])
            csv_writer.writeheader()
            for i in range(42):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['mineralogize'] = 'yes'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('ContentPersonAllegation')

            # When I submit the setup form
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

            # Then I should see a CSV Preview with the first few lines from my CSV
            csv_preview_element = wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-csv-preview')
            self.assertIn(
                'mineralogize',
                csv_preview_element.text
            )
            self.assertIn(
                os.path.basename(csv_fd.name),
                csv_preview_element.text
            )

            # and the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'ContentPersonAllegation',
                info_card_element.text
            )

            # and the Status Guide should say that the batch is loaded and ready to validate, with a 'Validate' button
            status_guide_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'Your batch has been set up. Now it needs to be validated.',
                status_guide_element.text
            )

            status_guide_element.find_element(By.CSS_SELECTOR, 'input[value="Validate Batch"]')

            # And I should not see the errors section
            with self.subTest(msg="No errors section"):
                with self.assertRaises(NoSuchElementException):
                    self.browser.find_element(By.CSS_SELECTOR, 'div.importer-errors')

            # And I should not see the rows section
            with self.subTest(msg="No imported rows section"):
                with self.assertRaises(NoSuchElementException):
                    self.browser.find_element(By.CSS_SELECTOR, 'div.importer-imported-rows')

    @override_settings(DEBUG=True, COMPRESS_ENABLED=True)
    def test_validate_post_validate_errors(self):
        """Test that the Info Card, Status Guide, General Errors Readout, Error Rows, and Error Rows ~Paginator~
        elements are displayed on the batch detail page when in the post-validate-errors state"""

        # Given I've set up a batch from the Import batch setup page containing an erroneous column
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement', 'not_a_legit_column_name'])
            csv_writer.writeheader()
            for i in range(5):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'BREAK'  # <-- bad value
                row['not_a_legit_column_name'] = "too legit to quit"
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('Person')
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

        # When I run the validation step
        wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Validate Batch"]') \
            .click()

        wait_until_dry_run_is_done()
        self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')
        # Confirm we're on the right page now
        wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-post-validate-errors')

        with self.subTest(msg="Info Card"):
            # Then I should see the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'Person',
                info_card_element.text
            )

        with self.subTest(msg="Status Guide"):
            # Then I should see the Status Guide with a "Start Over" button
            status_guide_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'Errors encountered during validation. Please correct errors and start a new batch.',
                status_guide_element.text
            )
            status_guide_element.find_element(By.LINK_TEXT, 'Start Over')

        # Then I should see an errors section
        errors_section = wait(self.browser.find_element_by_css_selector, 'div.importer-errors')
        with self.subTest(msg="General Errors Readout"):
            # and it should contain an error about the erroneous column
            self.assertIn(
                "ERROR: 'not_a_legit_column_name' not a valid column name for Person imports",
                errors_section.text
            )
        with self.subTest(msg="Error Rows"):
            # and it should contain 5 row level errors (limited by pagination)
            self.assertEqual(
                5,
                errors_section.text.count("Enter a valid boolean value")
            )
            # # and the row level errors paginator
            # self.browser.find_element(By.CSS_SELECTOR, 'nav[aria-label="Pagination"]')

        # And I should not see the imported rows section
        with self.subTest(msg="No imported rows section"):
            with self.assertRaises(NoSuchElementException):
                self.browser.find_element(By.CSS_SELECTOR, 'div.importer-imported-rows')

    @override_settings(DEBUG=True, COMPRESS_ENABLED=True)
    def test_validate_post_validate_ready(self):
        """Test that the Info Card and Status Guide are displayed and no other elements on the batch detail page
        when in the post-validate-ready state"""

        # Given I've set up a batch from the Import batch setup page that has no erroneous rows or invalid cells
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(3):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'True'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('Person')
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

        # When I run the validation step
        wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Validate Batch"]') \
            .click()

        sleep(1)  # Match sleep of redirect javascript
        # Confirm we're on the right page now
        wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-post-validate-ready')

        with self.subTest(msg="Status Guide"):
            # Then I should see the Status Guide with an Import X rows button
            status_guide_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'No errors were encountered during validation. Ready to import.',
                status_guide_element.text
            )
            status_guide_element.find_element(By.CSS_SELECTOR, 'input[value="Import 3 rows"]')

        with self.subTest(msg="Info Card"):
            # Then I should see the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'Person',
                info_card_element.text
            )

        # And I should not see the errors section
        with self.subTest(msg="No errors section"):
            with self.assertRaises(NoSuchElementException):
                self.browser.find_element(By.CSS_SELECTOR, 'div.importer-errors')

        # And I should not see the imported rows section
        with self.subTest(msg="No imported rows section"):
            with self.assertRaises(NoSuchElementException):
                self.browser.find_element(By.CSS_SELECTOR, 'div.importer-imported-rows')

    @override_settings(DEBUG=True, COMPRESS_ENABLED=True)
    def test_mid_import(self):
        """Test that the Info Card and Status Guide are displayed with a note about import being in progress when in
        the mid-import state"""

        # Given I've set up a batch and validated it successfully
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(3):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'True'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('Person')
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Validate Batch"]') \
                .click()


            # When I click the "Import X rows button"
            wait_until_dry_run_is_done()
            self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')
            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Import 3 rows"]') \
                .click()

        # ... artificially force batch back into 'mid-import' state
        wait_until_import_is_done()
        batch = ImportBatch.objects.last()
        batch.completed = None
        batch.save()
        # ... and go back to the detail page
        self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')

        with self.subTest(msg="Status Guide"):
            # Then I should see the Status Guide with a message that says "Import in progress"
            status_guide_element = wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'Import in progress',
                status_guide_element.text
            )

        with self.subTest(msg="Info Card"):
            # Then I should see the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'Person',
                info_card_element.text
            )

    @override_settings(DEBUG=True, COMPRESS_ENABLED=True)
    def test_post_import_failed(self):
        """Test that Info Card, Status Guide, Row Errors, and ~Paginator~ are present but not All Rows when in the
        post-import-failed state"""

        # Given I've set up a batch from the Import batch setup page containing foreign key errors
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['subject_person', 'type', 'object_person'])
            csv_writer.writeheader()
            for i in range(5):
                row = {}
                row['subject_person'] = 1  # <- Doesn't exist
                row['type'] = 'Test Type'
                row['object_person'] = 2  # <- Doesn't exist
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('PersonRelationship')
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Validate Batch"]') \
                .click()

            wait_until_dry_run_is_done()
            self.browser.refresh()
            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Import 5 rows"]') \
                .click()

        # Jump back to the detail page now that the import has completed in the background -- side stepping the
        # mid-import page for this test.
        wait_until_import_is_done()
        self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')
        # Confirm we're on the right page now
        wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-post-import-failed')

        with self.subTest(msg="Info Card"):
            # Then I should see the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'PersonRelationship',
                info_card_element.text
            )

        with self.subTest(msg="Status Guide"):
            # Then I should see the Status Guide with a "Start Over" button
            status_guide_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'Import failed. No records were imported.',
                status_guide_element.text
            )
            status_guide_element.find_element(By.LINK_TEXT, 'Start Over')

        # Then I should see an errors section
        errors_section = wait(self.browser.find_element_by_css_selector, 'div.importer-errors')
        with self.subTest(msg="Error Rows"):
            # and it should contain 5 row level errors
            self.assertEqual(
                5,
                errors_section.text.count("Person matching query does not exist")
            )
            # # and the row level errors paginator
            # self.browser.find_element(By.CSS_SELECTOR, 'nav[aria-label="Pagination"]')

        # And I should not see the imported rows section
        with self.subTest(msg="No imported rows section"):
            with self.assertRaises(NoSuchElementException):
                self.browser.find_element(By.CSS_SELECTOR, 'div.importer-imported-rows')

    @override_settings(DEBUG=True, COMPRESS_ENABLED=True)
    def test_complete(self):
        """Test that Info Card, All Rows, and Status Guide, but not Row Errors are present when in the complete
        state"""

        # Given I've set up a batch from the Import batch setup page containing NO errors
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as csv_fd:
            imported_records = []
            csv_writer = csv.DictWriter(csv_fd, ['name', 'is_law_enforcement'])
            csv_writer.writeheader()
            for i in range(5):
                row = {}
                row['name'] = f'Test Person {uuid4()}'
                row['is_law_enforcement'] = 'checked'
                csv_writer.writerow(row)
                imported_records.append(row)
            csv_fd.flush()  # Make sure it's actually written to the filesystem!

            self.log_in(is_administrator=True)
            self.browser.get(self.live_server_url + reverse('importer_narwhal:new-batch'))
            wait(self.browser.find_element_by_css_selector, 'input#id_import_sheet') \
                .send_keys(csv_fd.name)
            Select(self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name')) \
                .select_by_visible_text('Person')
            self.browser.find_element(By.CSS_SELECTOR, 'select#id_target_model_name').submit()

            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Validate Batch"]') \
                .click()

            wait_until_dry_run_is_done()
            self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')
            wait(self.browser.find_element, By.CSS_SELECTOR, 'input[value="Import 5 rows"]') \
                .click()

        wait_until_import_is_done()
        # Jump back to the detail page now that the import has completed in the background -- side stepping the
        # mid-import page for this test.
        self.browser.get(self.live_server_url + f'/changing/importer/batch/{ImportBatch.objects.last().pk}')
        # Confirm we're on the right page now
        wait(self.browser.find_element, By.CSS_SELECTOR, 'div.importer-complete')

        with self.subTest(msg="Info Card"):
            # Then I should see the Info Card with details of my submission
            info_card_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-info-card')
            self.assertIn(
                os.path.basename(csv_fd.name),
                info_card_element.text
            )
            self.assertIn(
                str(len(imported_records)),
                info_card_element.text
            )
            self.assertIn(
                'Person',
                info_card_element.text
            )

        with self.subTest(msg="Status Guide"):
            # Then I should see the Status Guide with a message saying the import completed successfully
            status_guide_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-status-guide')
            self.assertIn(
                'Import completed successfully',
                status_guide_element.text
            )

        with self.subTest(msg='Imported rows section'):
            imported_rows_element = self.browser.find_element(By.CSS_SELECTOR, 'div.importer-imported-rows')
            self.assertIn(
                imported_records[1]['name'],
                imported_rows_element.text
            )
