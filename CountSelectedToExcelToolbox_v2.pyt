# -*- coding: utf-8 -*-
import arcpy
import os
import openpyxl


class Toolbox(object):
    def __init__(self):
        self.label = "Count Selected Features to Excel Toolbox v2"
        self.alias = "CountSelectedToExcel_v2"
        self.tools = [CountSelectedToExcel]


class CountSelectedToExcel(object):
    def __init__(self):
        self.label = "Count Selected Features to Excel"
        self.description = "Counts selected features in a layer and appends the count to an Excel file."
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = [
            arcpy.Parameter(
                displayName="Input Layer",
                name="input_layer",
                datatype="GPFeatureLayer",
                parameterType="Required",
                direction="Input"
            ),
            arcpy.Parameter(
                displayName="Output Excel File (e.g., C:\\Output\\result.xlsx)",
                name="output_excel",
                datatype="DEFile",
                parameterType="Required",
                direction="Input"
            )
        ]
        params[1].filter.list = ["xlsx"]
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        input_layer = parameters[0].valueAsText
        output_excel = parameters[1].valueAsText

        # Check if the layer has selected features
        desc = arcpy.Describe(input_layer)
        layer_name = desc.name

        selected_count = int(arcpy.management.GetCount(input_layer).getOutput(0))

        arcpy.AddMessage(f"Selected Features Count: {selected_count}")

        # Create Excel file if it doesn't exist
        if not os.path.exists(output_excel):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Counts"
            ws.append(["Row", "Selected_Count"])
            wb.save(output_excel)
            arcpy.AddMessage(f"Excel file created at {output_excel}")
        else:
            wb = openpyxl.load_workbook(output_excel)
            ws = wb.active

        # Determine the next row number
        next_row = ws.max_row  # Header is row 1

        ws.append([next_row, selected_count])
        wb.save(output_excel)

        arcpy.AddMessage(f"✅ Row {next_row}, Count {selected_count} saved to {output_excel}")
