import os
import re
import shutil
import requests
import pymupdf as fitz

from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote

MUNICIPIO_ID = 31

BASE_URL = "https://plenussistemas.dioenet.com.br"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}

PASTA_TEMP = "temp"
PASTA_SAIDA = "saida"

os.makedirs(PASTA_TEMP, exist_ok=True)
os.makedirs(PASTA_SAIDA, exist_ok=True)


def obter_ultimas_publicacoes(limite=10):

    url = "https://plenussistemas.dioenet.com.br/list/taubate"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    html = response.text

    ids = re.findall(r'/uploads/view/(\d+)', html)

    ids = list(dict.fromkeys(ids))

    publicacoes = []

    for edicao_id in ids[:limite]:
        publicacoes.append({"id": int(edicao_id)})

    return publicacoes


def obter_pdf_da_edicao(edicao_id):

    url = f"{BASE_URL}/uploads/view/{edicao_id}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    iframe = soup.find("iframe")

    if not iframe:
        return None

    src = iframe.get("src", "")

    parsed = urlparse(src)

    parametros = parse_qs(parsed.query)

    arquivo_pdf = parametros.get("file")

    if not arquivo_pdf:
        return None

    return unquote(arquivo_pdf[0])


def baixar_pdf(url, destino):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=120
    )

    response.raise_for_status()

    with open(destino, "wb") as arquivo:
        arquivo.write(response.content)


def extrair_contratada(texto_limpo, processo_norm):

    pares = re.findall(
        r"CONTRATADA:\s*(.*?)\s*PROCESSO:\s*([\d./-]+)",
        texto_limpo
    )

    for contratada, num_processo in pares:

        num_processo_norm = re.sub(r"\D", "", num_processo)

        if num_processo_norm == processo_norm:
            return contratada.strip(" -")

    return None


def extrair_empresa_despacho(page, texto_norm, processo, ocorrencias):
    """No despacho, a empresa vem depois do cabeçalho 'PROCESSO Nº ...' e vai
    do ':' de 'empresa:' até a primeira vírgula (também aceita 'firma ...,').
    A busca fica limitada ao bloco do processo, até o próximo cabeçalho."""

    digitos = re.sub(r"\D", "", processo)
    padrao = r"[.\s/-]*".join(re.escape(d) for d in digitos)

    m_proc = re.search(padrao, texto_norm)

    if not m_proc:
        return None, []

    inicio = m_proc.end()

    proximo = re.search(
        r"PROCESSO\s*N\S{0,3}\s*\d",
        texto_norm[inicio:],
        re.IGNORECASE
    )

    fim = inicio + proximo.start() if proximo else len(texto_norm)

    trecho = texto_norm[inicio:fim]

    m = re.search(
        r"EMPRESA:\s*([^,]+),|FIRMA:?\s+([^,]+),",
        trecho,
        re.IGNORECASE
    )

    if not m:
        return None, []

    nome = (m.group(1) or m.group(2)).strip()

    candidatos = page.search_for(nome)

    if not candidatos:
        return nome, []

    alvo = ocorrencias[0]
    centro_alvo = (alvo.y0 + alvo.y1) / 2

    mais_proximo = min(
        candidatos,
        key=lambda r: abs((r.y0 + r.y1) / 2 - centro_alvo)
    )

    # inclui linhas consecutivas do mesmo nome (empresa quebrada em duas linhas)
    grupo = [mais_proximo]

    for r in sorted(candidatos, key=lambda r: r.y0):
        if r in grupo:
            continue
        if any(abs(r.y0 - g.y1) <= 4 or abs(g.y0 - r.y1) <= 4 for g in grupo):
            grupo.append(r)

    return nome, grupo


def localizar_processo(doc, processo, modo="extrato"):

    if modo == "extrato":
        padrao_pagina = re.compile(r"EXTRATO")
    else:
        # aceita "DESPACHO" e também "D E S P A C H O" (letras espaçadas)
        padrao_pagina = re.compile(r"D ?E ?S ?P ?A ?C ?H ?O")

    processo_norm = re.sub(r"\D", "", processo)

    for pagina_num in range(len(doc)):

        page = doc[pagina_num]

        texto = page.get_text("text")

        texto_limpo = re.sub(r"\s+", " ", texto.upper())

        if not padrao_pagina.search(texto_limpo):
            continue

        texto_norm = re.sub(r"\D", "", texto_limpo)

        if processo_norm not in texto_norm:
            continue

        ocorrencias = page.search_for(processo)

        if not ocorrencias:
            numeros = re.sub(r"[^0-9]", "", processo)
            if numeros:
                ocorrencias = page.search_for(numeros)

        if not ocorrencias:
            continue

        if modo == "extrato":

            entidade = extrair_contratada(texto_limpo, processo_norm)

            areas_entidade = []

            if entidade:

                todas = page.search_for(entidade)

                areas_entidade = [
                    area_c for area_c in todas
                    if any(
                        abs(area_c.y0 - area_p.y0) <= 3
                        for area_p in ocorrencias
                    )
                ]

        else:

            texto_original = re.sub(r"\s+", " ", texto)

            entidade, areas_entidade = extrair_empresa_despacho(
                page, texto_original, processo, ocorrencias
            )

        return {
            "pagina": pagina_num,
            "areas": ocorrencias,
            "entidade": entidade,
            "areas_entidade": areas_entidade,
            "texto": texto
        }

    return None


def gerar_pdf_destacado(pdf_origem, processo, pdf_destino, modo="extrato"):

    doc = fitz.open(pdf_origem)

    resultado = localizar_processo(doc, processo, modo)

    if not resultado:
        doc.close()
        return None

    pagina = resultado["pagina"]

    page = doc[pagina]

    areas_para_grifar = list(resultado["areas"]) + list(resultado["areas_entidade"])

    for area in areas_para_grifar:
        annot = page.add_highlight_annot(area)
        annot.update()

    novo_pdf = fitz.open()

    novo_pdf.insert_pdf(doc, from_page=pagina, to_page=pagina)

    novo_pdf.save(pdf_destino)

    novo_pdf.close()
    doc.close()

    return {
        "pagina": pagina + 1,
        "arquivo": pdf_destino,
        "entidade": resultado["entidade"]
    }


def buscar_processo(processo, dias=5, modo="extrato",
                    pasta_temp=None, pasta_saida=None, log=print):
    """pasta_temp/pasta_saida/log são opcionais: a versão web usa pastas
    temporárias por consulta e um log próprio, sem interferir em outros usuários."""

    pasta_temp = pasta_temp or PASTA_TEMP
    pasta_saida = pasta_saida or PASTA_SAIDA

    os.makedirs(pasta_temp, exist_ok=True)
    os.makedirs(pasta_saida, exist_ok=True)

    dias = max(1, min(10, dias))

    publicacoes = obter_ultimas_publicacoes(limite=dias)

    if not publicacoes:
        log("Nenhuma publicação retornada.")
        return None

    for pub in publicacoes:

        try:
            edicao_id = pub["id"]

            log(f"Analisando edição {edicao_id}")

            pdf_url = obter_pdf_da_edicao(edicao_id)

            if not pdf_url:
                continue

            pdf_local = os.path.join(pasta_temp, f"edicao_{edicao_id}.pdf")

            baixar_pdf(pdf_url, pdf_local)

            nome_seguro = re.sub(r"[^a-zA-Z0-9_-]", "_", processo)

            pdf_final = os.path.join(pasta_saida, f"Processo_{nome_seguro}_{modo}.pdf")

            resultado = gerar_pdf_destacado(pdf_local, processo, pdf_final, modo)

            if os.path.exists(pdf_local):
                os.remove(pdf_local)

            if resultado:
                log()
                log("=" * 70)
                log(f"PROCESSO ENCONTRADO ({modo.upper()})")
                log("=" * 70)
                log(f"Edição: {edicao_id}")
                log(f"Página: {resultado['pagina']}")
                if resultado.get("entidade"):
                    log(f"Grifado: {resultado['entidade']}")
                log(f"PDF Gerado: {resultado['arquivo']}")
                log("PDF Original:")
                log(pdf_url)
                log()
                log("Link direto:")
                log(f"{pdf_url}#page={resultado['pagina']}")

                resultado["edicao_id"] = edicao_id
                resultado["pdf_url"] = pdf_url
                resultado["link_direto"] = f"{pdf_url}#page={resultado['pagina']}"

                return resultado

        except Exception as erro:
            log(f"Erro na edição {pub.get('id')}")
            log(str(erro))

    log(f"\nProcesso não localizado em {modo} nas últimas {dias} publicações.")
    return None


def limpar_temporarios():

    try:
        if os.path.exists(PASTA_TEMP):
            shutil.rmtree(PASTA_TEMP)
    except Exception:
        pass


if __name__ == "__main__":

    processo = input("Número do processo: ").strip()

    try:
        buscar_processo(processo)
    finally:
        limpar_temporarios()
