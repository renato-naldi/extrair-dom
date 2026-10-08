import re
import tempfile

import streamlit as st

st.set_page_config(
    page_title="Buscar Processo - Diário Oficial de Taubaté",
    page_icon="📄",
    layout="centered",
)

st.title("📄 Buscar Processo")
st.caption("Diário Oficial do Município de Taubaté")

if "resultado" not in st.session_state:
    st.session_state.resultado = None
    st.session_state.log = ""
    st.session_state.erro = None


def executar_busca(processo, modo, dias):

    # Importados aqui (e não no topo) para a tela aparecer primeiro e
    # qualquer falha de importação ser exibida em vez de deixar a página em branco.
    try:
        import pymupdf as fitz
        import extrai_v3
    except Exception as erro:
        st.session_state.resultado = None
        st.session_state.erro = f"Falha ao carregar os módulos: {erro!r}"
        return

    linhas = []

    def log(texto=""):
        linhas.append(str(texto))

    st.session_state.resultado = None
    st.session_state.erro = None

    with tempfile.TemporaryDirectory() as pasta:

        try:
            resultado = extrai_v3.buscar_processo(
                processo,
                dias=dias,
                modo=modo,
                pasta_temp=f"{pasta}/temp",
                pasta_saida=f"{pasta}/saida",
                log=log,
            )

            if resultado:

                with open(resultado["arquivo"], "rb") as arquivo:
                    pdf_bytes = arquivo.read()

                with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                    previa = doc[0].get_pixmap(dpi=110).tobytes("png")

                nome_seguro = re.sub(r"[^a-zA-Z0-9_-]", "_", processo)

                st.session_state.resultado = {
                    "pdf": pdf_bytes,
                    "previa": previa,
                    "nome": f"Processo_{nome_seguro}_{modo}.pdf",
                    "pagina": resultado["pagina"],
                    "edicao": resultado["edicao_id"],
                    "grifado": resultado.get("entidade"),
                    "link": resultado["link_direto"],
                }

        except Exception as erro:
            st.session_state.erro = str(erro)

    st.session_state.log = "\n".join(linhas)


def limpar():
    st.session_state.resultado = None
    st.session_state.erro = None
    st.session_state.log = ""
    st.session_state.campo_processo = ""


with st.form("form_busca"):

    processo = st.text_input(
        "Número do processo",
        key="campo_processo",
        placeholder="Ex.: 24.523/2026",
        max_chars=30,
    )

    col1, col2 = st.columns(2)

    modo = col1.radio(
        "Pesquisar em",
        options=["extrato", "despacho"],
        format_func=lambda m: {
            "extrato": "Extrato (processo + contratada)",
            "despacho": "Despacho (processo + empresa)",
        }[m],
    )

    dias = col2.number_input(
        "Dias de pesquisa (máx. 10)",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )

    col_buscar, col_limpar, _ = st.columns([1, 1, 3])

    enviar = col_buscar.form_submit_button("Buscar", type="primary")
    col_limpar.form_submit_button("Limpar", on_click=limpar)

if enviar:

    processo = processo.strip()

    if not re.search(r"\d", processo):
        st.warning("Digite o número do processo.")
    else:
        with st.spinner("Consultando as edições do Diário Oficial..."):
            executar_busca(processo, modo, int(dias))

resultado = st.session_state.resultado

if resultado:

    st.success(
        f"Processo encontrado — edição {resultado['edicao']}, "
        f"página {resultado['pagina']}."
    )

    if resultado["grifado"]:
        st.write(f"**Grifado junto ao processo:** {resultado['grifado']}")

    st.image(resultado["previa"], width="stretch")

    st.download_button(
        "⬇️ Baixar PDF grifado",
        data=resultado["pdf"],
        file_name=resultado["nome"],
        mime="application/pdf",
    )

    st.markdown(f"[Abrir a edição original no Diário Oficial]({resultado['link']})")

elif st.session_state.erro:
    st.error(f"Erro: {st.session_state.erro}")

elif enviar and re.search(r"\d", processo):
    st.info("Processo não localizado nas edições pesquisadas.")

if st.session_state.log:
    with st.expander("Detalhes da consulta"):
        st.code(st.session_state.log, language=None)
