from markitdoc.pdf.pages import WHITE
from markitdoc.visuals.photo_fit import fitted_image

MEASURING_PHOTO = "measuring photo"


# places a cropped photo on the PDF page and adds its credit when available
def placed(pdf, image, x, y, width, height, work_folder, fades=(), description="Photograph"):
    if image == MEASURING_PHOTO:
        return
    pdf.image(fitted_image(image, width, height, work_folder, fades, pdf.photos, pdf.theme, pdf.photo_focus), x, y, width, height,
              alt_text=description)
    if pdf.photo_credit:
        credit_on_photo(pdf, x, y, width, height, *pdf.photo_credit)


# draws a compact photo credit over the bottom corner of the image
def credit_on_photo(pdf, x, y, width, height, credit, source):
    pdf.set_font("Brand", "", 5.5)
    text = credit if pdf.get_string_width(credit) < width - 8 else credit.split(",")[0]
    text_width = pdf.get_string_width(text) + 3
    left, top = x + width - text_width - 2, y + height - 6
    with pdf.local_context(fill_opacity=0.45):
        pdf.set_fill_color(0, 0, 0)
        pdf.rect(left, top, text_width, 4.2, "F")
    pdf.set_text_color(*WHITE)
    pdf.set_xy(left + 1.5, top + 0.6)
    pdf.cell(text_width - 3, 3, text, link=source)
