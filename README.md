# Leitor de Remessas

Aplicativo Streamlit para ler manifestos de carga em PDF, revisar a extracao e gerar a planilha de cargas pendentes.

## Como rodar

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## O que mudou

- Parser separado em `remessa_parser.py`, facilitando teste e manutencao.
- Suporte a PDF com multiplas remessas e paginas de continuacao.
- Validacao de campos obrigatorios com alertas na tela.
- Previa editavel antes do download.
- Exportacao XLSX em memoria, sem criar arquivos temporarios soltos.
- Normalizacao de transportadoras, clientes, NF, cidade, peso, valor e volume.
