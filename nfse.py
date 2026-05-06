"""
nfse.py — Emissão de NFS-e via Focus NFe
Clínica DTM & Sono — Dr. Victor Vaz
"""
import os, base64, json, requests
from datetime import datetime
from pathlib import Path

FOCUSNFE_TOKEN    = os.environ.get("FOCUSNFE_TOKEN", "")
FOCUSNFE_AMBIENTE = os.environ.get("FOCUSNFE_AMBIENTE", "homologacao")
CERT_A1_PATH      = os.environ.get("CERT_A1_PATH", "")
CERT_A1_B64       = os.environ.get("CERT_A1_B64", "")
CERT_A1_SENHA     = os.environ.get("CERT_A1_SENHA", "")

BASE_URL_PROD  = "https://api.focusnfe.com.br"
BASE_URL_HOMOL = "https://homologacao.focusnfe.com.br"

CLINICAS_CONFIG = {
    1: {"nome": "Clínica DTM & Sono — Balneário Camboriú", "cnpj": os.environ.get("CNPJ_BC", ""), "codigo_municipio": "4202008", "codigo_servico": "0401", "aliquota_iss": 0.03, "regime_tributario": "1"},
    2: {"nome": "Clínica DTM & Sono — São José dos Campos", "cnpj": os.environ.get("CNPJ_SJC", ""), "codigo_municipio": "3549904", "codigo_servico": "0401", "aliquota_iss": 0.03, "regime_tributario": "1"}
}

def _base_url(): return BASE_URL_PROD if FOCUSNFE_AMBIENTE == "producao" else BASE_URL_HOMOL
def _auth(): return (FOCUSNFE_TOKEN, "")
def _cert_bytes():
    if CERT_A1_PATH and Path(CERT_A1_PATH).exists(): return Path(CERT_A1_PATH).read_bytes()
    if CERT_A1_B64: return base64.b64decode(CERT_A1_B64)
    return None
def _limpar_doc(doc): return "".join(c for c in (doc or "") if c.isdigit())
def _ref_unica(): return f"DTMSONO-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
def _tipo_documento(doc): return "CPF" if len(_limpar_doc(doc)) == 11 else "CNPJ"

def cadastrar_certificado(cnpj):
    cert = _cert_bytes()
    if not cert: return {"ok": False, "erro": "Certificado A1 não encontrado."}
    if not CERT_A1_SENHA: return {"ok": False, "erro": "Senha do certificado não configurada."}
    cnpj_limpo = _limpar_doc(cnpj)
    resp = requests.put(f"{_base_url()}/v2/empresas/{cnpj_limpo}/certificado", auth=_auth(),
                        json={"certificado": base64.b64encode(cert).decode(), "certificado_senha": CERT_A1_SENHA}, timeout=30)
    if resp.status_code in (200, 201): return {"ok": True, "mensagem": "Certificado cadastrado com sucesso"}
    return {"ok": False, "erro": f"Erro {resp.status_code}: {resp.text}"}

def emitir_nfse(clinica_id, tomador_nome, tomador_doc, servico_descricao, valor, tomador_email="", tomador_telefone="", tomador_endereco=None):
    cfg = CLINICAS_CONFIG.get(clinica_id)
    if not cfg: return {"ok": False, "erro": f"Clínica {clinica_id} não configurada"}
    if not cfg["cnpj"]: return {"ok": False, "erro": f"CNPJ da clínica {clinica_id} não configurado"}
    if not FOCUSNFE_TOKEN: return {"ok": False, "erro": "FOCUSNFE_TOKEN não configurado"}
    ref = _ref_unica()
    cnpj_emit = _limpar_doc(cfg["cnpj"])
    doc_tom = _limpar_doc(tomador_doc) if tomador_doc else ""
    aliquota = cfg["aliquota_iss"]
    valor_iss = round(valor * aliquota, 2)
    payload = {
        "data_emissao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "prestador": {"cnpj": cnpj_emit, "codigo_municipio": cfg["codigo_municipio"]},
        "tomador": {"razao_social": tomador_nome, "email": tomador_email, "telefone": _limpar_doc(tomador_telefone) if tomador_telefone else ""},
        "servico": {"aliquota": aliquota, "base_calculo": valor, "discriminacao": servico_descricao, "iss_retido": False, "item_lista_servico": cfg["codigo_servico"], "valor_iss": valor_iss, "valor_liquido": valor, "valor_servicos": valor, "codigo_municipio": cfg["codigo_municipio"]},
        "natureza_operacao": 1,
    }
    if doc_tom:
        tipo = _tipo_documento(doc_tom)
        payload["tomador"]["cpf" if tipo == "CPF" else "cnpj"] = doc_tom
    if tomador_endereco:
        payload["tomador"]["endereco"] = tomador_endereco
    try:
        resp = requests.post(f"{_base_url()}/v2/{cnpj_emit}/nfse?ref={ref}", auth=_auth(), json=payload, timeout=60)
        data = resp.json()
    except requests.exceptions.Timeout:
        return {"ok": False, "ref": ref, "erro": "Timeout na comunicação com Focus NFe"}
    except Exception as e:
        return {"ok": False, "ref": ref, "erro": str(e)}
    status = data.get("status", "")
    if resp.status_code in (200, 201) and status in ("autorizado", "processando_autorizacao"):
        return {"ok": True, "ref": ref, "status": status, "numero": data.get("numero", ""), "codigo_verificacao": data.get("codigo_verificacao", ""), "pdf_url": data.get("caminho_xml_nota_fiscal", ""), "xml_url": data.get("caminho_xml_nota_fiscal", "")}
    erros = data.get("erros", [])
    msg_erro = "; ".join(e.get("mensagem", str(e)) for e in erros) if erros else data.get("mensagem", str(data))
    return {"ok": False, "ref": ref, "status": status, "erro": msg_erro}

def consultar_nfse(cnpj_emitente, ref):
    cnpj = _limpar_doc(cnpj_emitente)
    try:
        resp = requests.get(f"{_base_url()}/v2/{cnpj}/nfse/{ref}", auth=_auth(), timeout=30)
        data = resp.json()
        return {"ok": resp.status_code == 200, "status": data.get("status", ""), "numero": data.get("numero", ""), "pdf_url": data.get("caminho_xml_nota_fiscal", ""), "erro": data.get("mensagem", "") if resp.status_code != 200 else ""}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

def cancelar_nfse(cnpj_emitente, ref, justificativa="Cancelamento solicitado pelo cliente"):
    cnpj = _limpar_doc(cnpj_emitente)
    try:
        resp = requests.delete(f"{_base_url()}/v2/{cnpj}/nfse/{ref}", auth=_auth(), json={"justificativa": justificativa}, timeout=30)
        if resp.status_code in (200, 204): return {"ok": True, "mensagem": "NFS-e cancelada com sucesso"}
        return {"ok": False, "erro": f"Erro {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

def testar_conexao():
    if not FOCUSNFE_TOKEN: return {"ok": False, "erro": "FOCUSNFE_TOKEN não configurado"}
    try:
        resp = requests.get(f"{_base_url()}/v2/empresas", auth=_auth(), timeout=10)
        if resp.status_code == 200: return {"ok": True, "ambiente": FOCUSNFE_AMBIENTE, "mensagem": "Conexão com Focus NFe OK"}
        return {"ok": False, "erro": f"Erro {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
