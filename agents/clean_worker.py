import os

def clean_worker():
    filepath = r"c:\Mentoria_V2\Consultoria_Empresarial_v2\agents\worker.py"
    if not os.path.exists(filepath):
        print("Arquivo worker.py não encontrado no caminho esperado.")
        return
        
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    # Encontrar as boundaries do bloco 1: Constantes duplicadas
    start_1 = None
    end_1 = None
    for i, line in enumerate(lines):
        if '# Modelo Realtime nativo do Gemini (voz-para-voz)' in line:
            start_1 = i
        if start_1 is not None and 'def _safe_publish_data' in line:
            end_1 = i - 1
            break
            
    # Encontrar as boundaries do bloco 2: Métodos Deprecated
    start_2 = None
    end_2 = None
    for i, line in enumerate(lines):
        if '# [DEPRECATED] Métodos internos do Marco' in line:
            start_2 = i - 1 # Pega a linha imediatamente acima (---)
        if start_2 is not None and i > start_2 and '*Documento gerado automaticamente pela plataforma' in line:
            # avançar algumas linhas até acabar a string tripla do markdown gerado e recuperar helper
            for j in range(i, len(lines)):
                if 'def _start_avatar_session' in lines[j]:
                    end_2 = j - 5  # Apaga até um pouco antes do helper de avatar
                    break
            break
            
    print(f"Bloco 1 (Constantes) detectado: Linha {start_1} a {end_1}")
    print(f"Bloco 2 (Deprecated Marco) detectado: Linha {start_2} a {end_2}")
    
    if None not in (start_1, end_1, start_2, end_2):
        new_lines = lines[:start_1] + lines[end_1+1:start_2] + lines[end_2+1:]
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("Limpeza concluída com sucesso! Foram removidas mais de 1000 linhas de código morto.")
    else:
        print("Aviso: Houve falha na deteção exata das linhas. O arquivo não foi modificado.")

if __name__ == "__main__":
    clean_worker()
