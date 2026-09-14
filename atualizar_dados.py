#!/usr/bin/env python3
"""
atualizar_dados.py
===================
Baixa a aba "CERTIFICADAS" da planilha pública do Google Sheets mantida por
Israel da Silva Oliveira, limpa e geocodifica os registros, e regenera o
arquivo index.html do painel Raizame Dados a partir de template.html.

Uso local:
    pip install requests
    python3 atualizar_dados.py

Este script é pensado para rodar dentro de uma GitHub Action agendada
(ver .github/workflows/atualizacao-semanal.yml), mas funciona igual
rodando na sua máquina.

Arquivos esperados no mesmo diretório:
    template.html   -> o template com os placeholders __TOTAL_REGISTROS__,
                        __TOTAL_COMUNIDADES__, __NAO_GEOCODIFICADOS__ e
                        __DATA_JSON__ (é o mesmo arquivo já usado até aqui,
                        sem os dados embutidos).

Gera:
    index.html       -> o painel completo, pronto para publicar.
"""

import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------
SHEET_ID = "1WBjixnnjJWrDXsA2WvElj65rrZ4nkNM-u5LclRV0lGs"
GID_CERTIFICADAS = "680278480"   # aba "CERTIFICADAS" (confirmado manualmente)
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID_CERTIFICADAS}"
MUNICIPIOS_URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

TEMPLATE_PATH = "template.html"
OUTPUT_PATH = "index.html"

UF_POR_CODIGO = {
    11: 'RO', 12: 'AC', 13: 'AM', 14: 'RR', 15: 'PA', 16: 'AP', 17: 'TO',
    21: 'MA', 22: 'PI', 23: 'CE', 24: 'RN', 25: 'PB', 26: 'PE', 27: 'AL',
    28: 'SE', 29: 'BA', 31: 'MG', 32: 'ES', 33: 'RJ', 35: 'SP', 41: 'PR',
    42: 'SC', 43: 'RS', 50: 'MS', 51: 'MT', 52: 'GO', 53: 'DF',
}

# Região é geografia fixa por UF, então qualquer divergência entre a coluna
# "Região" da planilha e a UF do registro pode ser corrigida sem ambiguidade
# nenhuma (a UF não tem essa mesma garantia, por isso não mexemos nela).
UF_PARA_REGIAO = {
    'AC': 'NORTE', 'AP': 'NORTE', 'AM': 'NORTE', 'PA': 'NORTE', 'RO': 'NORTE', 'RR': 'NORTE', 'TO': 'NORTE',
    'AL': 'NORDESTE', 'BA': 'NORDESTE', 'CE': 'NORDESTE', 'MA': 'NORDESTE', 'PB': 'NORDESTE',
    'PE': 'NORDESTE', 'PI': 'NORDESTE', 'RN': 'NORDESTE', 'SE': 'NORDESTE',
    'DF': 'CENTRO-OESTE', 'GO': 'CENTRO-OESTE', 'MT': 'CENTRO-OESTE', 'MS': 'CENTRO-OESTE',
    'ES': 'SUDESTE', 'MG': 'SUDESTE', 'RJ': 'SUDESTE', 'SP': 'SUDESTE',
    'PR': 'SUL', 'RS': 'SUL', 'SC': 'SUL',
}


def corrige_regioes(registros):
    """Corrige a coluna 'regiao' com base na UF (fato geográfico, sem
    ambiguidade) e devolve a lista de correções feitas, para documentar
    de forma transparente na própria página."""
    correcoes = []
    for r in registros:
        uf = r['uf'].strip().upper()
        regiao_correta = UF_PARA_REGIAO.get(uf)
        if regiao_correta and r['regiao'].strip().upper() != regiao_correta:
            correcoes.append({
                'municipio': r['municipio'], 'comunidade': r['comunidade'], 'uf': uf,
                'regiao_original': r['regiao'].strip().title(),
                'regiao_corrigida': regiao_correta.title(),
                'processo': r['processo'], 'ano': r['ano'],
            })
            r['regiao'] = regiao_correta
    if correcoes:
        print(f"{len(correcoes)} divergência(s) entre Região e UF corrigida(s) automaticamente.")
    return correcoes

# mapeia o cabeçalho exato da planilha (como está hoje) para o nosso
# nome de campo interno. Se a FCP renomear uma coluna, é só ajustar aqui.
MAPA_COLUNAS = {
    'REGIÃO': 'regiao',
    'UF': 'uf',
    'MUNICÍPIO': 'municipio',
    'CÓDIGO DO IBGE': 'ibge',
    'COMUNIDADE': 'comunidade',
    'Nº PROCESSO NA FCP': 'processo',
    'DATA DA ABERTURA': 'abertura',
    'Nº DO LIVRO DE REGISTRO': 'livro',
    'Nº DO REGISTRO': 'registro',
    'Nº DA FOLHA': 'folha',
    'Nº DA PORTARIA': 'portaria',
    'DATA DA PORTARIA NO DOU': 'dataPortaria',
    'RETIFICAÇÃO NO DOU': 'retificacao',
    'Nº PROCESSO INCRA': 'processoIncra',
    'ETAPA DO PROCESSO DE TITULAÇÃO': 'etapa',
    'Nº DE CRQ': 'crq',
    'Nº DE MORADORES': 'moradores',
    'POPULAÇÃO IBGE': 'popIbge',
    'ANO CERTIFICAÇÃO': 'ano',
    'PORTA DE ENTRADA': 'porta',
}


def baixar_texto(url):
    req = urllib.request.Request(url, headers={"User-Agent": "raizame-dados-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = resp.read()
    # o export do Google vem em UTF-8 com BOM às vezes
    return dados.decode("utf-8-sig")


def normaliza_cabecalho(h):
    # remove espaços duplicados e invisíveis para casar com MAPA_COLUNAS
    # mesmo se a FCP adicionar/tirar um espaço um dia
    h2 = re.sub(r"\s+", " ", h.replace("\xa0", " ")).strip()
    return h2


def limpa_valor(v):
    if v is None:
        return ""
    v = v.replace("\xa0", "").replace("\u200b", "").strip()
    return v


def converte_data(v):
    """DD/MM/AAAA (como a planilha exibe) -> AAAA-MM-DD (o que o painel espera).
    Se vier em outro formato ou vazio, devolve como está / vazio."""
    v = limpa_valor(v)
    if not v:
        return ""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", v)
    if m:
        d, mo, a = m.groups()
        try:
            return datetime(int(a), int(mo), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            return v
    m2 = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
    if m2:
        return v
    return v  # datas compostas tipo "19/05/2005 - 25/04/2006" ficam como texto


def baixar_certificadas():
    print(f"Baixando planilha: {CSV_URL}")
    texto = baixar_texto(CSV_URL)
    leitor = csv.reader(io.StringIO(texto))
    linhas = list(leitor)
    if not linhas:
        raise RuntimeError("Planilha vazia ou inacessível.")

    cabecalho_bruto = linhas[0]
    cabecalho = [normaliza_cabecalho(h) for h in cabecalho_bruto]
    indices = {}
    for campo_planilha, campo_interno in MAPA_COLUNAS.items():
        if campo_planilha in cabecalho:
            indices[campo_interno] = cabecalho.index(campo_planilha)
        else:
            print(f"AVISO: coluna '{campo_planilha}' não encontrada no cabeçalho atual da planilha. "
                  f"Esse campo ficará vazio em todos os registros até o mapeamento ser corrigido.")

    registros = []
    for linha in linhas[1:]:
        if not any(c.strip() for c in linha):
            continue  # linha em branco
        def pega(campo):
            i = indices.get(campo)
            if i is None or i >= len(linha):
                return ""
            return limpa_valor(linha[i])

        regiao = pega('regiao')
        comunidade = pega('comunidade')
        if not regiao and not comunidade:
            continue

        registros.append({
            "regiao": regiao,
            "uf": pega('uf'),
            "municipio": pega('municipio'),
            "ibge": pega('ibge'),
            "comunidade": comunidade,
            "processo": pega('processo'),
            "abertura": converte_data(pega('abertura')),
            "livro": pega('livro'),
            "registro": pega('registro'),
            "folha": pega('folha'),
            "portaria": pega('portaria'),
            "dataPortaria": converte_data(pega('dataPortaria')),
            "retificacao": pega('retificacao'),
            "processoIncra": pega('processoIncra'),
            "etapa": pega('etapa'),
            "crq": pega('crq'),
            "moradores": pega('moradores'),
            "popIbge": pega('popIbge'),
            "ano": pega('ano'),
            "porta": pega('porta'),
        })

    print(f"{len(registros)} registros lidos da planilha.")
    return registros


# ----------------------------------------------------------------------
# GEOCODIFICAÇÃO (mesma lógica usada na primeira versão do painel)
# ----------------------------------------------------------------------
def normaliza_nome(s):
    s = s.upper().strip()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Z ]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def carrega_coordenadas():
    print(f"Baixando tabela de coordenadas municipais: {MUNICIPIOS_URL}")
    texto = baixar_texto(MUNICIPIOS_URL)
    leitor = csv.DictReader(io.StringIO(texto))
    por_codigo, por_nome_uf = {}, {}
    for linha in leitor:
        lat, lon = float(linha['latitude']), float(linha['longitude'])
        uf = UF_POR_CODIGO.get(int(linha['codigo_uf']), '')
        # guarda também a UF e o nome do município do código, para conseguirmos
        # detectar quando o código IBGE da planilha aponta para outro município
        por_codigo[linha['codigo_ibge']] = (lat, lon, uf, linha['nome'])
        por_nome_uf[(normaliza_nome(linha['nome']), uf)] = (lat, lon)
    print(f"{len(por_codigo)} municípios carregados.")
    return por_codigo, por_nome_uf


def extrai_codigos(ibge_bruto):
    if not ibge_bruto:
        return []
    partes = re.split(r'[|/,\n]', ibge_bruto)
    return [p.strip() for p in partes if p.strip()]


def geocodifica(registros, por_codigo, por_nome_uf):
    """Geocodifica cada registro por município. Quando o código IBGE informado
    na planilha aponta para um município de outra UF (ex.: código de Curaçá/BA
    usado num registro de Curuçá/PA — nomes parecidos, municípios diferentes),
    o código é descartado e a geocodificação cai para busca por nome + UF do
    próprio registro, que é o dado em que dá pra confiar nesse caso. Cada
    ocorrência é registrada em `correcoes_geo` para aparecer na página."""
    sem_coordenada = 0
    correcoes_geo = []
    for r in registros:
        uf_registro = r['uf'].strip().upper()
        coord = None
        codigo_encontrado_no_dicionario = False
        for codigo in extrai_codigos(r['ibge']):
            codigo_limpo = re.sub(r'\D', '', codigo)
            if codigo_limpo in por_codigo:
                codigo_encontrado_no_dicionario = True
                lat, lon, uf_do_codigo, nome_do_codigo = por_codigo[codigo_limpo]
                if uf_do_codigo == uf_registro:
                    coord = (lat, lon)
                else:
                    # código não bate com a UF do registro: não confia nele,
                    # tenta resolver pelo nome do município + UF do registro
                    primeiro_municipio = re.split(r'[|/]', r['municipio'])[0].strip()
                    alternativa = por_nome_uf.get((normaliza_nome(primeiro_municipio), uf_registro))
                    correcoes_geo.append({
                        'municipio': r['municipio'], 'comunidade': r['comunidade'], 'uf': uf_registro,
                        'codigo_informado': codigo_limpo, 'municipio_do_codigo': nome_do_codigo,
                        'uf_do_codigo': uf_do_codigo, 'processo': r['processo'], 'ano': r['ano'],
                        'resolvido': alternativa is not None,
                    })
                    coord = alternativa
                break  # já achou um código presente no dicionário, não olha os demais
        if not codigo_encontrado_no_dicionario:
            # nenhum dos códigos da célula existe no dicionário: tenta direto por nome + UF
            primeiro_municipio = re.split(r'[|/]', r['municipio'])[0].strip()
            coord = por_nome_uf.get((normaliza_nome(primeiro_municipio), uf_registro))
        if coord:
            r['lat'], r['lon'] = round(coord[0], 4), round(coord[1], 4)
        else:
            r['lat'], r['lon'] = None, None
            sem_coordenada += 1
    if correcoes_geo:
        print(f"{len(correcoes_geo)} código(s) IBGE incompatível(is) com a UF do registro; geocodificação recalculada por nome + UF.")
    print(f"{sem_coordenada} registro(s) não geocodificado(s).")
    return sem_coordenada, correcoes_geo


# ----------------------------------------------------------------------
# GERAÇÃO DO index.html
# ----------------------------------------------------------------------
def gera_pagina(registros, sem_coordenada, correcoes, correcoes_geo):
    with open(TEMPLATE_PATH, encoding='utf-8') as f:
        tpl = f.read()

    total_registros = len(registros)
    total_comunidades = sum(int(r['crq']) if r['crq'].isdigit() else 0 for r in registros)
    data_hoje = datetime.now(timezone.utc).strftime('%d/%m/%Y')

    tpl = tpl.replace('__TOTAL_REGISTROS__', f'{total_registros:,}'.replace(',', '.'))
    tpl = tpl.replace('__TOTAL_COMUNIDADES__', f'{total_comunidades:,}'.replace(',', '.'))
    tpl = tpl.replace('__NAO_GEOCODIFICADOS__', str(sem_coordenada))
    tpl = tpl.replace('__DATA_ATUALIZACAO__', data_hoje)
    tpl = tpl.replace('__CORRECOES_JSON__', json.dumps(correcoes, ensure_ascii=False))
    tpl = tpl.replace('__CORRECOES_GEO_JSON__', json.dumps(correcoes_geo, ensure_ascii=False))
    tpl = tpl.replace('__DATA_JSON__', json.dumps(registros, ensure_ascii=False))

    restantes = re.findall(r'__[A-Z_]+__', tpl)
    if restantes:
        raise RuntimeError(f"Placeholders não substituídos: {restantes}")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(tpl)

    print(f"{OUTPUT_PATH} gerado: {total_registros} certidões, {total_comunidades} comunidades, "
          f"data {data_hoje}, {len(correcoes)} correção(ões) de região, "
          f"{len(correcoes_geo)} correção(ões) de geocodificação.")


def main():
    registros = baixar_certificadas()
    if len(registros) < 1000:
        # trava de segurança: se a planilha vier vazia ou cortada por algum
        # erro de rede/permissão, é melhor abortar do que publicar uma base
        # incompleta por cima da anterior
        print(f"ERRO: só vieram {len(registros)} registros (esperado bem mais que 1000). "
              f"Abortando sem sobrescrever {OUTPUT_PATH}.")
        sys.exit(1)

    por_codigo, por_nome_uf = carrega_coordenadas()
    sem_coordenada, correcoes_geo = geocodifica(registros, por_codigo, por_nome_uf)
    correcoes = corrige_regioes(registros)
    gera_pagina(registros, sem_coordenada, correcoes, correcoes_geo)


if __name__ == "__main__":
    main()
