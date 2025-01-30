import requests
import os
import json
import csv
import subprocess
import msvcrt
from datetime import datetime, timedelta

# Caminho para o arquivo batch que lista os arquivos no SFTP
sftp_batch_file = 'C:\\Users\\keys\\list_files.bat'

# Comando para sincronizar arquivos usando o Duck CLI
duck_command = (
    'duck --username "Seu username aqui" --synchronize "sftp://sftp.uber.com:2222/from_uber/trips/" '
    '"C:\\Users\\keys\\UberTrips" --identity "C:\\Users\\keys\\private.pem"'
)

# Caminho para o arquivo JSON com credenciais da API do Notion
notion_credenciais_json = "C:\\Users\\Scripts\\notion_credenciais.json"

# Carrega as credenciais da API do Notion a partir do arquivo JSON
with open(notion_credenciais_json, 'r', encoding='utf-8') as nc:
    notion_credenciais = json.load(nc)

# Extrai a chave da API e o ID do banco de dados do Notion
NOTION_API_KEY = notion_credenciais["Uber_Business_Key"]
NOTION_DATABASE_ID = notion_credenciais["Registro_de_Despesas_ID"]

# Caminho para o arquivo JSON que mapeia e-mails para IDs de usuários no Notion
notion_users_json = "C:\\Users\\Scripts\\notion_users.json"

# Carrega o mapeamento de e-mails para IDs de usuários no Notion
with open(notion_users_json, 'r', encoding='utf-8') as nu:
    notion_user_map = json.load(nu)

# Mensagem de orientação que será incluída nas entradas do Notion
orientacoes = '''Orientações do financeiro:
Essa tarefa foi criada automaticamente com base nas suas despesas recentes. Por favor, atualize o título, preencha os campos necessários e anexe os documentos correspondentes para a prestação de contas ao time financeiro.
Não é necessário criar um novo card para a mesma despesa. Em caso de dúvidas, entre em contato com o time financeiro.'''

try:
    # Executa o comando SFTP para listar arquivos manualmente
    print("Conectando via SFTP...")
    subprocess.run(sftp_batch_file, shell=True, check=True)

    # Executa o comando Duck para sincronizar os arquivos
    print("Sincronizando arquivos com o Duck...")

    # Utiliza o subprocess para enviar o comando e a opção de download automaticamente
    process = subprocess.Popen(duck_command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate(input='download\n')

    # Verifica se a sincronização foi bem-sucedida
    if process.returncode == 0:
        print("Sincronização concluída com sucesso.")

        def retrieve_all_notion_uuids():
            """
            Recupera todos os UUIDs existentes no banco de dados do Notion.
            Isso é usado para evitar a criação de entradas duplicadas.
            """
            try:
                headers = {
                    "Authorization": f"Bearer {NOTION_API_KEY}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28"
                }

                url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

                all_uuids = []
                has_more = True
                next_cursor = None

                # Loop para paginar os resultados da API do Notion
                while has_more:
                    payload = {"page_size": 100}
                    if next_cursor:
                        payload["start_cursor"] = next_cursor

                    response = requests.post(url, headers=headers, json=payload)
                    if response.status_code != 200:
                        print(f"Erro ao buscar UUIDs do Notion: {response.status_code} - {response.reason}")
                        msvcrt.getch()
                        exit()

                    data = response.json()
                    results = data.get('results', [])

                    # Extrai os UUIDs das entradas existentes
                    for entry in results:
                        properties = entry.get('properties', {})
                        if 'UUID' in properties and 'rich_text' in properties['UUID'] and properties['UUID']['rich_text']:
                            all_uuids.append(properties['UUID']['rich_text'][0]['text']['content'])

                    has_more = data.get('has_more', False)
                    next_cursor = data.get('next_cursor', None)
                return all_uuids
            except requests.exceptions.RequestException as e:
                print(f"Erro ao buscar UUIDs do Notion: {e}")
                msvcrt.getch()
                exit()

        def create_notion_entry(row, existing_entries):
            """
            Cria uma nova entrada no Notion com base nos dados de uma linha do CSV.
            Verifica se o UUID já existe para evitar duplicações.
            """
            uuid = row.get("ID da viagem/Uber Eats")
            if not uuid:
                print(f"UUID não encontrado ou inválido na linha: {row}")
                return False
            if uuid in existing_entries:
                print(f"UUID {uuid} já existe no Notion. Pulando.")
                return False

            # Corrige o formato da data
            date_str = row.get("Data da solicitação (local)", "")
            try:
                # Converte a data para o formato ISO-8601 esperado pelo Notion
                date_iso = datetime.strptime(date_str, "%m/%d/%Y").date().isoformat()
            except ValueError:
                print(f"Formato de data inválido: {date_str}")
                return False

            # Constrói o título da entrada no Notion
            servico = row.get("Serviço", "")
            titulo = f"Código - Despesa a identificar (Uber Business) {servico}"

            # Recupera o ID do usuário no Notion com base no e-mail
            email = row.get("E-mail", "").strip().lower()
            user_id = notion_user_map.get(email, None)

            # Prepara os dados para criar a entrada no Notion
            notion_data = {
                "parent": {"database_id": NOTION_DATABASE_ID},
                "properties": {
                    "Orientações": {"rich_text": [{"text": {"content": orientacoes}}]},
                    "UUID": {"rich_text": [{"text": {"content": uuid}}]},
                    "Nome": {"title": [{"text": {"content": titulo}}]},  # Usando o novo título
                    "Data de Pagamento": {"date": {"start": date_iso}},  # Data no formato ISO-8601
                    "Nome do Usuário": {"rich_text": [{"text": {"content": f"{row.get('Nome', '')} {row.get('Sobrenome', '')}"}}]},
                    "E-mail": {"rich_text": [{"text": {"content": row.get("E-mail", "")}}]},
                    "Valor": {"number": float(row.get("Valor da transação em BRL (com tributos)", 0))},
                    "Moeda": {"rich_text": [{"text": {"content": row.get("Código da moeda local", "BRL")}}]},
                    "Responsável": {"people": [{"id": user_id}]} if user_id else {"people": []}
                }
            }

            try:
                # Envia a requisição para criar a entrada no Notion
                response = requests.post("https://api.notion.com/v1/pages", headers={
                    "Authorization": f"Bearer {NOTION_API_KEY}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28"
                }, json=notion_data)
                response.raise_for_status()
                print(f"Nova entrada criada no Notion para UUID: {uuid}")
                return True
            except requests.exceptions.RequestException as e:
                print(f"Erro ao criar entrada no Notion para UUID {uuid}: {e}")
                return False

        def process_csv_files(directory):
            """
            Processa os arquivos CSV no diretório especificado.
            Filtra arquivos dos últimos 10 dias e cria entradas no Notion.
            """
            # Define a data limite (10 dias atrás a partir de hoje)
            today = datetime.now().date()
            ten_days_ago = today - timedelta(days=10)

            # Recupera todos os UUIDs existentes no Notion
            existing_entries = retrieve_all_notion_uuids()

            # Itera sobre os arquivos CSV no diretório
            for file_name in os.listdir(directory):
                if file_name.endswith('.csv'):
                    # Extrai a data do nome do arquivo no formato "daily_trips-YYYY_MM_DD.csv"
                    try:
                        file_date_str = file_name.split('-')[1]  # Pega "YYYY_MM_DD.csv"
                        file_date = datetime.strptime(file_date_str, "%Y_%m_%d.csv").date()

                        # Verifica se o arquivo está dentro dos últimos 10 dias
                        if file_date < ten_days_ago:
                            print(f"Arquivo {file_name} fora do intervalo de 10 dias. Ignorando.")
                            continue

                    except (IndexError, ValueError):
                        print(f"Nome de arquivo {file_name} não segue o formato esperado. Ignorando.")
                        continue

                    # Caminho completo do arquivo
                    file_path = os.path.join(directory, file_name)
                    print(f"Processando arquivo: {file_path}")

                    # Abre o arquivo CSV e processa as linhas
                    with open(file_path, newline='', encoding='utf-8') as csvfile:
                        reader = csv.reader(csvfile, delimiter=';')

                        # Ignora as primeiras 6 linhas (cabeçalhos)
                        for _ in range(6):
                            next(reader)

                        # Processa as linhas restantes
                        for row in reader:
                            if len(row) < 45:  # Verifica se há colunas suficientes
                                print(f"Linha ignorada, número de colunas insuficientes: {row}")
                                continue

                            # Cria um dicionário com os dados da linha
                            row_dict = {
                                "ID da viagem/Uber Eats": row[0] if len(row) > 0 else '',
                                "Data da solicitação (local)": row[4] if len(row) > 4 else '',
                                "Nome": row[11] if len(row) > 11 else '',
                                "Sobrenome": row[12] if len(row) > 12 else '',
                                "E-mail": row[13] if len(row) > 13 else '',
                                "Valor da transação em BRL (com tributos)": row[36] if len(row) > 36 else '',
                                "Código da moeda local": row[32] if len(row) > 32 else '',
                                "Serviço": row[15] if len(row) > 15 else '',  # Adiciona o campo "Serviço"
                            }
                            # Cria uma entrada no Notion para a linha atual
                            create_notion_entry(row_dict, existing_entries)

        def main():
            """Função principal que inicia o processamento dos arquivos CSV."""
            csv_directory = "C:\\Users\\keys\\UberTrips"
            process_csv_files(csv_directory)

        if __name__ == "__main__":
            main()

    else:
        print(f"Erro ao executar o comando Duck: {stderr}")

except subprocess.CalledProcessError as e:
    print(f"Erro ao executar o comando: {e}")

# Aguarda a pressão de qualquer tecla para encerrar o script
print("Pressione qualquer tecla para encerrar...")
msvcrt.getch()