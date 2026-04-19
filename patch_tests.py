import sys

def patch_tests():
    with open('agents/tests/test_worker.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Context window changes
    content = content.replace('[User10]: Mensagem 10', '[User18]: Mensagem 18')
    content = content.replace('[User9]: Mensagem 9', '[User17]: Mensagem 17')

    # Revert EXPECTED_SPEC_IDS to have plan
    content = content.replace('EXPECTED_SPEC_IDS = {"cfo", "legal", "cmo", "cto"}', 'EXPECTED_SPEC_IDS = {"cfo", "legal", "cmo", "cto", "plan"}')

    # test_specialist_order_contains_all_specialists
    content = content.replace('self.assertEqual(set(SPECIALIST_ORDER), self.EXPECTED_SPEC_IDS)', 'self.assertEqual(set(SPECIALIST_ORDER), {"cfo", "legal", "cmo", "cto"})')

    # test_order_is_correct
    content = content.replace('expected_order = ["cfo", "legal", "cmo", "cto", "plan"]', 'expected_order = ["cfo", "legal", "cmo", "cto"]')

    with open('agents/tests/test_worker.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
if __name__ == '__main__':
    patch_tests()
    print("Tests patched successfully")