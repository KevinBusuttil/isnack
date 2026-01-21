# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

from isnack.overrides.batch import validate_batch_spaces


class TestValidateBatchSpaces(unittest.TestCase):
    """Tests for validate_batch_spaces function."""
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_batch_spaces_converted_to_underscore(self, mock_process):
        """Test that spaces in batch_id are converted to underscores."""
        # Setup mock
        mock_process.return_value = "BATCH_001"
        
        # Create a mock Batch document
        doc = MagicMock()
        doc.batch_id = "BATCH 001"
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was called with the original batch_id
        mock_process.assert_called_once_with("BATCH 001")
        
        # Assert that the batch_id was updated
        self.assertEqual(doc.batch_id, "BATCH_001")
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_batch_spaces_converted_to_dash(self, mock_process):
        """Test that spaces in batch_id are converted to dashes."""
        # Setup mock
        mock_process.return_value = "BATCH-002"
        
        # Create a mock Batch document
        doc = MagicMock()
        doc.batch_id = "BATCH 002"
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was called with the original batch_id
        mock_process.assert_called_once_with("BATCH 002")
        
        # Assert that the batch_id was updated
        self.assertEqual(doc.batch_id, "BATCH-002")
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_batch_no_spaces_unchanged(self, mock_process):
        """Test that batch_id without spaces remains unchanged."""
        # Setup mock
        mock_process.return_value = "BATCH003"
        
        # Create a mock Batch document
        doc = MagicMock()
        doc.batch_id = "BATCH003"
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was called
        mock_process.assert_called_once_with("BATCH003")
        
        # Assert that the batch_id was NOT updated (since it's the same)
        self.assertEqual(doc.batch_id, "BATCH003")
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_empty_batch_id(self, mock_process):
        """Test that empty batch_id is handled correctly."""
        # Create a mock Batch document with empty batch_id
        doc = MagicMock()
        doc.batch_id = ""
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was NOT called for empty batch_id
        mock_process.assert_not_called()
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_none_batch_id(self, mock_process):
        """Test that None batch_id is handled correctly."""
        # Create a mock Batch document with None batch_id
        doc = MagicMock()
        doc.batch_id = None
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was NOT called for None batch_id
        mock_process.assert_not_called()
    
    @patch('isnack.overrides.batch._process_batch_spaces')
    def test_batch_with_multiple_spaces(self, mock_process):
        """Test that batch_id with multiple spaces is processed correctly."""
        # Setup mock
        mock_process.return_value = "BATCH_MULTI_SPACE_TEST"
        
        # Create a mock Batch document
        doc = MagicMock()
        doc.batch_id = "BATCH MULTI SPACE TEST"
        
        # Call the validation function
        validate_batch_spaces(doc)
        
        # Assert that _process_batch_spaces was called
        mock_process.assert_called_once_with("BATCH MULTI SPACE TEST")
        
        # Assert that the batch_id was updated
        self.assertEqual(doc.batch_id, "BATCH_MULTI_SPACE_TEST")


if __name__ == "__main__":
    unittest.main()
