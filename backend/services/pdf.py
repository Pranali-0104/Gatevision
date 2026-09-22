from fpdf import FPDF

def generate_pdf(records):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    for r in records:
        pdf.cell(200, 8, txt=str(r), ln=True)

    return pdf.output(dest='S').encode('latin-1')