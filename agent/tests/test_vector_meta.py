import unittest
from unittest import mock

from agent.config import vector_conf


class VectorMetaTests(unittest.TestCase):
    def test_provider_prefixed_names_match_the_same_index(self):
        with mock.patch.object(vector_conf, "load_meta", return_value={"embedding_model": "bge-m3", "vector_dim": 1024}):
            vector_conf.assert_meta_matches("Pro/BAAI/bge-m3", 1024)
            vector_conf.assert_meta_matches("BAAI/bge-m3", 1024)
            with self.assertRaises(RuntimeError):
                vector_conf.assert_meta_matches("Qwen/Qwen3-Embedding-4B", 1024)
            with self.assertRaises(RuntimeError):
                vector_conf.assert_meta_matches("Pro/BAAI/bge-m3", 2560)


if __name__ == "__main__":
    unittest.main()
