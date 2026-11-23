import csv
with open("relatorio_etiquetas_agrupado.csv", mode='r') as f:
    leitor = csv.DictReader(f)
    for c in leitor:
        print(c['etiqueta'], c['quantidade_pdfs']) 
