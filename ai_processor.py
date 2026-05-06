"""
ai_processor.py — Processamento de linguagem natural via Claude API
Clínica DTM & Sono — Dr. Victor Vaz
"""
import os
import json
import base64
from datetime import datetime
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

SYSTEM_PROMPT = """Você é a IA de gestão da Clínica DTM & Sono do Dr. Victor Vaz, especialista em DTM, sono, bruxismo e saúde integrativa. Você gerencia financeiro, leads e notas fiscais das unidades de Balneário Camboriú/SC e São José dos Campos/SP.

Sua função é interpretar mensagens da secretaria em linguagem natural e retornar um JSON estruturado com a ação a executar.

CATEGORIAS DE DESPESA VÁLIDAS:
Aluguel, Folha de Pagamento, Insumos, Marketing, Contador, Equipamentos, Software, Impostos/Taxas, Cursos/Capacitação, Outras

ORIGENS DE LEAD VÁLIDAS:
Meta Ads, Google Ads, Indicação, Orgânico/Instagram, Site, WhatsApp, Outro

Retorne SEMPRE um JSON válido no seguinte formato:

{
  "acao": "<tipo da ação>",
  "dados": { <campos extraídos> },
  "confirmacao": "<mensagem curta de confirmação para a secretária>",
  "duvida": "<se algo ficou ambíguo, pergunte aqui — caso contrário null>"
}

TIPOS DE AÇÃO e campos esperados:

1. "registrar_despesa"
   dados: { categoria, subtipo (Fixa|Variável), descricao, valor (número), data (YYYY-MM-DD) }

2. "registrar_receita"
   dados: { descricao, valor (número), data (YYYY-MM-DD), paciente (se mencionado) }

3. "registrar_lead"
   dados: { nome, telefone (se mencionado), origem, observacoes (se houver) }

4. "atualizar_lead"
   dados: { nome (para identificar), campo (agendou|compareceu|virou_paciente|contato_feito), valor (true|false), data_consulta (se agendamento) }

5. "emitir_nota"
   dados: { tomador_nome, tomador_doc (CPF/CNPJ se mencionado), servico, valor (número) }

6. "registrar_anuncio"
   dados: { plataforma (Meta Ads|Google Ads), mes (número), investimento, impressoes, cliques, leads, agendamentos, novos_pacientes }

7. "consulta"
   dados: { tipo (financeiro|leads|notas|geral), periodo (mes/ano se mencionado) }

8. "upload_comprovante"
   dados: { tipo (despesa|receita|outro), categoria (se identificável na imagem) }

9. "indefinido"
   dados: {}

REGRAS:
- Se o valor estiver em formato "R$ 3.500,00" ou "3500 reais" ou "3,5k" → converta para número float
- Se a data não for mencionada, use hoje
- Se o mês não for mencionado em anúncios, use o mês atual
- Seja conciso na confirmação (máx 2 linhas)
- Se tiver dúvida sobre algo importante (valor, clínica), pergunte na chave "duvida"
- Nunca invente valores ou nomes que não foram mencionados"""


def processar_mensagem(texto: str, clinica_nome: str, data_hoje: str = None) -> dict:
    if not data_hoje:
        data_hoje = datetime.now().strftime("%Y-%m-%d")
    user_content = f"[Clínica: {clinica_nome}] [Data de hoje: {data_hoje}]\n\nMensagem da secretária: {texto}"
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}]
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"acao": "indefinido", "dados": {}, "confirmacao": "Não entendi bem essa mensagem. Pode reformular?", "duvida": None}
    except Exception as e:
        return {"acao": "erro", "dados": {}, "confirmacao": f"Erro de comunicação com a IA: {str(e)}", "duvida": None}


def processar_imagem(image_bytes: bytes, mime_type: str, clinica_nome: str) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}},
                {"type": "text", "text": f"[Clínica: {clinica_nome}] [Data de hoje: {data_hoje}]\n\nEsta é uma imagem de comprovante enviada pela secretária. Identifique o tipo (despesa/receita), valor, data, descrição e categoria se possível. Retorne a ação upload_comprovante com os dados extraídos."}
            ]}]
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        return {"acao": "upload_comprovante", "dados": {"tipo": "outro", "categoria": "Outras"}, "confirmacao": "Comprovante recebido e salvo. Não consegui ler os detalhes automaticamente.", "duvida": None}


def gerar_resumo(dados: dict, clinica_nome: str) -> str:
    prompt = f"""Com base nos dados financeiros abaixo da {clinica_nome}, gere um resumo executivo em 3-4 frases em português, destacando pontos de atenção e performance.

Dados:
{json.dumps(dados, ensure_ascii=False, indent=2)}

Seja direto e objetivo. Destaque o resultado líquido, a maior despesa, e o CAC se disponível."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception:
        return "Resumo indisponível no momento."
