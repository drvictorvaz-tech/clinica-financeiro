"""
main.py — Backend principal (FastAPI)
Clínica DTM & Sono — Dr. Victor Vaz
"""
import os, json, shutil, hashlib, secrets
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import (FastAPI, Request, Form, File, UploadFile,
                     HTTPException, Depends, Cookie, Response)
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_conn, row_to_dict
from ai_processor import processar_mensagem, processar_imagem, gerar_resumo
from nfse import emitir_nfse, consultar_nfse, testar_conexao, CLINICAS_CONFIG

def _load_dotenv():
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

UPLOAD_DIR     = Path(os.environ.get("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
sessions: dict = {}

app = FastAPI(title="Clínica DTM & Sono — Sistema IA", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static",  StaticFiles(directory="static"),        name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

@app.on_event("startup")
def startup():
    init_db()
    _ensure_admin()

def _ensure_admin():
    admin_pw = os.environ.get("ADMIN_PASSWORD", "dtmadmin2025")
    h = _hash(admin_pw)
    conn = get_conn()
    conn.execute("UPDATE users SET senha_hash=? WHERE email='admin@clinicadtm.com.br'", (h,))
    conn.commit(); conn.close()

def _hash(pw): return hashlib.sha256(pw.encode()).hexdigest()

def get_session(token: Optional[str] = Cookie(default=None, alias="session")):
    if not token or token not in sessions: return None
    return sessions[token]

def require_auth(session=Depends(get_session)):
    if not session: raise HTTPException(status_code=401, detail="Não autenticado")
    return session

def require_admin(session=Depends(get_session)):
    if not session or session.get("papel") != "admin": raise HTTPException(status_code=403, detail="Acesso negado")
    return session

def save_upload(file, clinica_id, categoria):
    now    = datetime.now()
    folder = UPLOAD_DIR / str(clinica_id) / str(now.year) / f"{now.month:02d}" / categoria
    folder.mkdir(parents=True, exist_ok=True)
    ts   = now.strftime("%Y%m%d_%H%M%S")
    path = folder / f"{ts}_{file.filename}"
    with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
    return str(path.relative_to(UPLOAD_DIR.parent))

@app.get("/",          response_class=HTMLResponse)
def index():      return FileResponse("static/index.html")
@app.get("/chat",      response_class=HTMLResponse)
def chat_page():  return FileResponse("static/chat.html")
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(): return FileResponse("static/dashboard.html")
@app.get("/admin",     response_class=HTMLResponse)
def admin_page(): return FileResponse("static/admin.html")

@app.post("/api/login")
async def login(request: Request):
    body  = await request.json()
    email = body.get("email", "").strip().lower()
    senha = body.get("senha", "")
    conn  = get_conn()
    user  = row_to_dict(conn.execute("SELECT * FROM users WHERE email=? AND ativo=1", (email,)).fetchone())
    conn.close()
    if not user or user["senha_hash"] != _hash(senha):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    token = secrets.token_hex(32)
    sessions[token] = {"user_id": user["id"], "nome": user["nome"], "papel": user["papel"], "clinica_id": user["clinica_id"]}
    resp = JSONResponse({"ok": True, "papel": user["papel"], "nome": user["nome"]})
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400*7)
    return resp

@app.post("/api/logout")
def logout(response: Response, session=Depends(get_session)):
    if session:
        for k, v in list(sessions.items()):
            if v == session: del sessions[k]
    response.delete_cookie("session")
    return {"ok": True}

@app.get("/api/me")
def me(session=Depends(require_auth)):
    conn    = get_conn()
    clinicas = [row_to_dict(r) for r in conn.execute("SELECT id, nome, cidade FROM clinicas WHERE ativo=1").fetchall()]
    conn.close()
    return {**session, "clinicas": clinicas}

@app.post("/api/chat")
async def chat(request: Request, session=Depends(require_auth)):
    body       = await request.json()
    texto      = body.get("mensagem", "").strip()
    clinica_id = body.get("clinica_id")
    if not texto: raise HTTPException(400, "Mensagem vazia")
    conn    = get_conn()
    clinica = row_to_dict(conn.execute("SELECT * FROM clinicas WHERE id=?", (clinica_id,)).fetchone())
    if not clinica: conn.close(); raise HTTPException(400, "Clínica inválida")
    resultado = processar_mensagem(texto, clinica["nome"])
    acao      = resultado.get("acao", "indefinido")
    dados     = resultado.get("dados", {})
    resposta  = resultado.get("confirmacao", "Processado.")
    if acao == "registrar_despesa":
        data_str = dados.get("data", date.today().isoformat())
        d = datetime.strptime(data_str[:10], "%Y-%m-%d")
        conn.execute("INSERT INTO transacoes (clinica_id,tipo,categoria,subtipo,descricao,valor,data,mes,ano,criado_por,origem_msg) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (clinica_id,"despesa",dados.get("categoria","Outras"),dados.get("subtipo","Variável"),dados.get("descricao",""),float(dados.get("valor",0)),data_str[:10],d.month,d.year,session["user_id"],texto))
        conn.commit()
    elif acao == "registrar_receita":
        data_str = dados.get("data", date.today().isoformat())
        d = datetime.strptime(data_str[:10], "%Y-%m-%d")
        conn.execute("INSERT INTO transacoes (clinica_id,tipo,categoria,descricao,valor,data,mes,ano,criado_por,origem_msg) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (clinica_id,"receita","Receita de Serviços",dados.get("descricao",""),float(dados.get("valor",0)),data_str[:10],d.month,d.year,session["user_id"],texto))
        conn.commit()
    elif acao == "registrar_lead":
        hoje = date.today()
        conn.execute("INSERT INTO leads (clinica_id,nome,telefone,origem,mes,ano,criado_por) VALUES (?,?,?,?,?,?,?)",
            (clinica_id,dados.get("nome","Sem nome"),dados.get("telefone",""),dados.get("origem","Outro"),hoje.month,hoje.year,session["user_id"]))
        conn.commit()
    elif acao == "atualizar_lead":
        nome = dados.get("nome",""); campo = dados.get("campo",""); valor = 1 if dados.get("valor") in [True,"true","True","Sim","sim"] else 0
        campos_validos = {"agendou","compareceu","virou_paciente","contato_feito"}
        if campo in campos_validos and nome:
            upd = f"{campo}=?"; params = [valor]
            if campo == "agendou" and dados.get("data_consulta"): upd += ", data_consulta=?"; params.append(dados["data_consulta"])
            params += [f"%{nome}%", clinica_id]
            conn.execute(f"UPDATE leads SET {upd}, atualizado_em=datetime('now') WHERE nome LIKE ? AND clinica_id=? ORDER BY criado_em DESC LIMIT 1", params)
            conn.commit()
    elif acao == "emitir_nota":
        tomador = dados.get("tomador_nome",""); doc_tom = dados.get("tomador_doc","")
        servico = dados.get("servico","Serviços Odontológicos — DTM/Sono/Bruxismo"); valor_nf = float(dados.get("valor",0))
        cfg_nfse = CLINICAS_CONFIG.get(clinica_id, {}); tem_config = bool(cfg_nfse.get("cnpj")) and bool(os.environ.get("FOCUSNFE_TOKEN"))
        if tem_config:
            resultado_nf = emitir_nfse(clinica_id=clinica_id, tomador_nome=tomador, tomador_doc=doc_tom, servico_descricao=servico, valor=valor_nf)
            if resultado_nf.get("ok"):
                num_nf = resultado_nf.get("numero","—"); status_nf = resultado_nf.get("status","autorizado")
                conn.execute("INSERT INTO notas_fiscais (clinica_id,tomador_nome,tomador_doc,servico,valor,data_emissao,numero_nfse,status,pdf_url,xml_url,criado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (clinica_id,tomador,doc_tom,servico,valor_nf,date.today().isoformat(),num_nf,status_nf,resultado_nf.get("pdf_url",""),resultado_nf.get("xml_url",""),session["user_id"]))
                conn.commit()
                resposta = "✅ NFS-e emitida!\n📋 Tomador: " + tomador + "\n💰 Valor: R$ " + str(valor_nf) + "\n🔢 Número: " + str(num_nf)
                if resultado_nf.get("pdf_url"): resposta += "\n📎 PDF: " + resultado_nf["pdf_url"]
            else:
                erro_msg = resultado_nf.get("erro","Erro desconhecido")
                conn.execute("INSERT INTO notas_fiscais (clinica_id,tomador_nome,tomador_doc,servico,valor,status,erro_msg,criado_por) VALUES (?,?,?,?,?,?,?,?)",
                    (clinica_id,tomador,doc_tom,servico,valor_nf,"erro",erro_msg,session["user_id"]))
                conn.commit(); resposta = "⚠️ Erro na emissão: " + erro_msg + "\nNota salva como pendente."
        else:
            conn.execute("INSERT INTO notas_fiscais (clinica_id,tomador_nome,tomador_doc,servico,valor,status,criado_por) VALUES (?,?,?,?,?,?,?)",
                (clinica_id,tomador,doc_tom,servico,valor_nf,"pendente",session["user_id"]))
            conn.commit(); resposta = "📋 Nota registrada como pendente:\n📋 " + tomador + "  💰 R$ " + str(valor_nf) + "\n⚠️ Configure CNPJ e FOCUSNFE_TOKEN para emitir automaticamente."
    elif acao == "registrar_anuncio":
        mes = int(dados.get("mes", date.today().month)); ano = int(dados.get("ano", date.today().year)); plat = dados.get("plataforma","Meta Ads")
        conn.execute("INSERT INTO anuncios (clinica_id,plataforma,mes,ano,investimento,impressoes,cliques,leads,agendamentos,novos_pacientes,criado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(clinica_id,plataforma,mes,ano) DO UPDATE SET investimento=excluded.investimento,impressoes=excluded.impressoes,cliques=excluded.cliques,leads=excluded.leads,agendamentos=excluded.agendamentos,novos_pacientes=excluded.novos_pacientes",
            (clinica_id,plat,mes,ano,float(dados.get("investimento",0)),int(dados.get("impressoes",0)),int(dados.get("cliques",0)),int(dados.get("leads",0)),int(dados.get("agendamentos",0)),int(dados.get("novos_pacientes",0)),session["user_id"]))
        conn.commit()
    conn.execute("INSERT INTO chat_log (user_id,clinica_id,mensagem,resposta,acao) VALUES (?,?,?,?,?)",
        (session["user_id"],clinica_id,texto,resposta,json.dumps(resultado)))
    conn.commit(); conn.close()
    return {"resposta": resposta, "acao": acao, "duvida": resultado.get("duvida")}

@app.post("/api/upload")
async def upload(clinica_id: int = Form(...), categoria: str = Form("Outras"), arquivo: UploadFile = File(...), session=Depends(require_auth)):
    mime = arquivo.content_type or "application/octet-stream"; content = await arquivo.read()
    ai_result = {}
    if mime.startswith("image/"):
        conn = get_conn(); clinica = row_to_dict(conn.execute("SELECT nome FROM clinicas WHERE id=?", (clinica_id,)).fetchone()); conn.close()
        if clinica: ai_result = processar_imagem(content, mime, clinica["nome"]); categoria = ai_result.get("dados",{}).get("categoria", categoria)
    arquivo.file.seek(0); caminho = save_upload(arquivo, clinica_id, categoria); hoje = date.today()
    conn = get_conn()
    conn.execute("INSERT INTO comprovantes (clinica_id,nome_arquivo,caminho,tipo,categoria,mes,ano,tamanho,criado_por) VALUES (?,?,?,?,?,?,?,?,?)",
        (clinica_id,arquivo.filename,caminho,ai_result.get("dados",{}).get("tipo","outro"),categoria,hoje.month,hoje.year,len(content),session["user_id"]))
    conn.commit(); conn.close()
    return {"ok": True, "caminho": caminho, "resposta": ai_result.get("confirmacao","Arquivo salvo com sucesso. ✅"), "dados": ai_result.get("dados",{})}

@app.get("/api/dashboard")
def dashboard(clinica_id: Optional[int] = None, mes: Optional[int] = None, ano: Optional[int] = None, session=Depends(require_auth)):
    hoje = date.today(); mes = mes or hoje.month; ano = ano or hoje.year
    if session["papel"] == "secretaria" and session["clinica_id"]: clinica_id = session["clinica_id"]
    conn = get_conn(); cf = "AND clinica_id=?" if clinica_id else ""
    pc = (mes,ano,clinica_id) if clinica_id else (mes,ano); py = (ano,clinica_id) if clinica_id else (ano,)
    fin = row_to_dict(conn.execute(f"SELECT SUM(CASE WHEN tipo='receita' THEN valor ELSE 0 END) AS receitas, SUM(CASE WHEN tipo='despesa' THEN valor ELSE 0 END) AS despesas FROM transacoes WHERE mes=? AND ano=? {cf}", pc).fetchone()) or {}
    cats = [row_to_dict(r) for r in conn.execute(f"SELECT categoria, SUM(valor) AS total FROM transacoes WHERE tipo='despesa' AND mes=? AND ano=? {cf} GROUP BY categoria ORDER BY total DESC", pc).fetchall()]
    leads = row_to_dict(conn.execute(f"SELECT COUNT(*) AS total, SUM(contato_feito) AS contatos, SUM(agendou) AS agendamentos, SUM(compareceu) AS comparecimentos, SUM(virou_paciente) AS pacientes FROM leads WHERE mes=? AND ano=? {cf}", pc).fetchone()) or {}
    ads = [row_to_dict(r) for r in conn.execute(f"SELECT plataforma, SUM(investimento) AS investimento, SUM(leads) AS leads, SUM(novos_pacientes) AS novos_pacientes FROM anuncios WHERE mes=? AND ano=? {cf} GROUP BY plataforma", pc).fetchall()]
    notas = [row_to_dict(r) for r in conn.execute(f"SELECT id,tomador_nome,servico,valor,status,data_emissao,numero_nfse,pdf_url FROM notas_fiscais WHERE strftime('%m',criado_em)=? AND strftime('%Y',criado_em)=? {cf} ORDER BY criado_em DESC LIMIT 20", (f"{mes:02d}",str(ano),clinica_id) if clinica_id else (f"{mes:02d}",str(ano))).fetchall()]
    mensal = [row_to_dict(r) for r in conn.execute(f"SELECT mes, SUM(CASE WHEN tipo='receita' THEN valor ELSE 0 END) AS receitas, SUM(CASE WHEN tipo='despesa' THEN valor ELSE 0 END) AS despesas FROM transacoes WHERE ano=? {cf} GROUP BY mes ORDER BY mes", py).fetchall()]
    comps = [row_to_dict(r) for r in conn.execute(f"SELECT id,nome_arquivo,caminho,categoria,tipo,criado_em FROM comprovantes WHERE mes=? AND ano=? {cf} ORDER BY criado_em DESC LIMIT 20", pc).fetchall()]
    conn.close()
    receitas = float(fin.get("receitas") or 0); despesas = float(fin.get("despesas") or 0)
    total_inv = sum(float(a.get("investimento") or 0) for a in ads); pac_ads = sum(int(a.get("novos_pacientes") or 0) for a in ads)
    return {"mes":mes,"ano":ano,"financeiro":{"receitas":receitas,"despesas":despesas,"resultado":receitas-despesas,"por_categoria":cats},"leads":leads,"anuncios":ads,"cac":round(total_inv/pac_ads,2) if pac_ads>0 else None,"notas":notas,"mensal":mensal,"comprovantes":comps}

@app.get("/api/admin/users")
def list_users(session=Depends(require_admin)):
    conn = get_conn(); rows = [row_to_dict(r) for r in conn.execute("SELECT u.id,u.nome,u.email,u.papel,u.ativo,u.clinica_id,c.nome AS clinica_nome FROM users u LEFT JOIN clinicas c ON u.clinica_id=c.id ORDER BY u.papel,u.nome").fetchall()]; conn.close(); return rows

@app.post("/api/admin/users")
async def create_user(request: Request, session=Depends(require_admin)):
    body = await request.json(); conn = get_conn()
    try:
        conn.execute("INSERT INTO users (nome,email,senha_hash,papel,clinica_id,ativo) VALUES (?,?,?,?,?,1)",
            (body["nome"],body["email"].lower(),_hash(body.get("senha","Clinica@2025")),body.get("papel","secretaria"),body.get("clinica_id")))
        conn.commit()
    except Exception as e: raise HTTPException(400, str(e))
    finally: conn.close()
    return {"ok": True}

@app.patch("/api/admin/users/{uid}")
async def update_user(uid: int, request: Request, session=Depends(require_admin)):
    body = await request.json(); conn = get_conn()
    if "ativo" in body: conn.execute("UPDATE users SET ativo=? WHERE id=?", (int(body["ativo"]),uid))
    if "senha" in body: conn.execute("UPDATE users SET senha_hash=? WHERE id=?", (_hash(body["senha"]),uid))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/api/comprovantes")
def listar_comprovantes(clinica_id: Optional[int] = None, mes: Optional[int] = None, ano: Optional[int] = None, session=Depends(require_auth)):
    hoje = date.today(); mes = mes or hoje.month; ano = ano or hoje.year
    if session["papel"] == "secretaria" and session["clinica_id"]: clinica_id = session["clinica_id"]
    conn = get_conn(); filt = "AND c.clinica_id=?" if clinica_id else ""; params = (mes,ano,clinica_id) if clinica_id else (mes,ano)
    rows = [row_to_dict(r) for r in conn.execute(f"SELECT c.*,cl.nome AS clinica_nome FROM comprovantes c JOIN clinicas cl ON c.clinica_id=cl.id WHERE c.mes=? AND c.ano=? {filt} ORDER BY c.criado_em DESC", params).fetchall()]
    conn.close(); return rows

@app.post("/api/notas/{nota_id}/reemitir")
async def reemitir_nota(nota_id: int, session=Depends(require_auth)):
    conn = get_conn(); nota = row_to_dict(conn.execute("SELECT * FROM notas_fiscais WHERE id=?", (nota_id,)).fetchone())
    if not nota: conn.close(); raise HTTPException(404, "Nota não encontrada")
    resultado_nf = emitir_nfse(clinica_id=nota["clinica_id"],tomador_nome=nota["tomador_nome"],tomador_doc=nota["tomador_doc"] or "",servico_descricao=nota["servico"],valor=float(nota["valor"]))
    if resultado_nf.get("ok"):
        conn.execute("UPDATE notas_fiscais SET status=?,numero_nfse=?,data_emissao=?,pdf_url=?,xml_url=?,erro_msg=NULL WHERE id=?",
            (resultado_nf.get("status","autorizado"),resultado_nf.get("numero",""),date.today().isoformat(),resultado_nf.get("pdf_url",""),resultado_nf.get("xml_url",""),nota_id))
    else:
        conn.execute("UPDATE notas_fiscais SET status='erro',erro_msg=? WHERE id=?", (resultado_nf.get("erro",""),nota_id))
    conn.commit(); conn.close(); return resultado_nf

@app.get("/api/notas/pendentes")
def listar_pendentes(session=Depends(require_admin)):
    conn = get_conn(); rows = [row_to_dict(r) for r in conn.execute("SELECT n.*,c.nome AS clinica_nome FROM notas_fiscais n JOIN clinicas c ON n.clinica_id=c.id WHERE n.status IN ('pendente','erro') ORDER BY n.criado_em DESC").fetchall()]; conn.close(); return rows

@app.get("/api/nfse/status")
def nfse_status(session=Depends(require_admin)):
    resultado = testar_conexao()
    config_ok = {cid: {"clinica": cfg["nome"], "cnpj_configurado": bool(cfg.get("cnpj"))} for cid, cfg in CLINICAS_CONFIG.items()}
    return {**resultado, "clinicas": config_ok}

@app.get("/api/health")
def health(): return {"status": "ok", "ts": datetime.now().isoformat()}
