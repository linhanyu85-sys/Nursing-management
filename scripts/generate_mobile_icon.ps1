$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$assetsRoot = Join-Path $projectRoot "apps\mobile\assets"
if (-not (Test-Path $assetsRoot)) {
  New-Item -ItemType Directory -Path $assetsRoot | Out-Null
}

function New-RoundedRectPath {
  param(
    [float]$X,
    [float]$Y,
    [float]$Width,
    [float]$Height,
    [float]$Radius
  )

  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $diameter = [Math]::Min($Radius * 2, [Math]::Min($Width, $Height))
  if ($diameter -le 0) {
    $path.AddRectangle([System.Drawing.RectangleF]::new($X, $Y, $Width, $Height))
    return $path
  }

  $arc = [System.Drawing.RectangleF]::new($X, $Y, $diameter, $diameter)
  $path.AddArc($arc, 180, 90)
  $arc.X = $X + $Width - $diameter
  $path.AddArc($arc, 270, 90)
  $arc.Y = $Y + $Height - $diameter
  $path.AddArc($arc, 0, 90)
  $arc.X = $X
  $path.AddArc($arc, 90, 90)
  $path.CloseFigure()
  return $path
}

function Fill-Diamond {
  param(
    [System.Drawing.Graphics]$Graphics,
    [System.Drawing.Brush]$Brush,
    [float]$CenterX,
    [float]$CenterY,
    [float]$Radius
  )

  $points = [System.Drawing.PointF[]]@(
    [System.Drawing.PointF]::new($CenterX, $CenterY - $Radius),
    [System.Drawing.PointF]::new($CenterX + $Radius, $CenterY),
    [System.Drawing.PointF]::new($CenterX, $CenterY + $Radius),
    [System.Drawing.PointF]::new($CenterX - $Radius, $CenterY)
  )
  $Graphics.FillPolygon($Brush, $points)
}

function Draw-Node {
  param(
    [System.Drawing.Graphics]$Graphics,
    [System.Drawing.Brush]$Brush,
    [float]$X,
    [float]$Y,
    [float]$R
  )

  $Graphics.FillEllipse($Brush, $X - $R, $Y - $R, $R * 2, $R * 2)
}

function Draw-AiIcon {
  param(
    [string]$OutputPath,
    [bool]$TransparentBackground
  )

  $size = 1024
  $bitmap = New-Object System.Drawing.Bitmap($size, $size)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

  if ($TransparentBackground) {
    $graphics.Clear([System.Drawing.Color]::Transparent)
  } else {
    $graphics.Clear([System.Drawing.Color]::FromArgb(255, 248, 250, 252))
  }

  $blueTop = [System.Drawing.Color]::FromArgb(255, 42, 163, 224)
  $blueBottom = [System.Drawing.Color]::FromArgb(255, 38, 118, 217)
  $linePen = New-Object System.Drawing.Pen($blueBottom, 42)
  $linePen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
  $nodeBrush = New-Object System.Drawing.SolidBrush($blueTop)
  $whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)

  $vertical = New-RoundedRectPath -X 316 -Y 84 -Width 392 -Height 856 -Radius 128
  $horizontal = New-RoundedRectPath -X 96 -Y 304 -Width 832 -Height 416 -Radius 128

  $gradientRect = [System.Drawing.RectangleF]::new(96, 84, 832, 856)
  $gradientBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $gradientRect,
    $blueTop,
    $blueBottom,
    [System.Drawing.Drawing2D.LinearGradientMode]::Vertical
  )

  $graphics.FillPath($gradientBrush, $vertical)
  $graphics.FillPath($gradientBrush, $horizontal)

  $innerVertical = New-RoundedRectPath -X 374 -Y 138 -Width 276 -Height 748 -Radius 88
  $innerHorizontal = New-RoundedRectPath -X 150 -Y 362 -Width 724 -Height 300 -Radius 88
  $graphics.FillPath($whiteBrush, $innerVertical)
  $graphics.FillPath($whiteBrush, $innerHorizontal)

  $plusVertical = New-RoundedRectPath -X 456 -Y 184 -Width 112 -Height 204 -Radius 28
  $plusHorizontal = New-RoundedRectPath -X 410 -Y 230 -Width 204 -Height 112 -Radius 28
  $graphics.FillPath($gradientBrush, $plusVertical)
  $graphics.FillPath($gradientBrush, $plusHorizontal)

  $chipRect = [System.Drawing.RectangleF]::new(486, 452, 260, 150)
  $chipBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    $chipRect,
    [System.Drawing.Color]::FromArgb(255, 49, 146, 229),
    [System.Drawing.Color]::FromArgb(255, 29, 96, 208),
    [System.Drawing.Drawing2D.LinearGradientMode]::Vertical
  )
  $chipPath = New-RoundedRectPath -X $chipRect.X -Y $chipRect.Y -Width $chipRect.Width -Height $chipRect.Height -Radius 24
  $graphics.FillPath($chipBrush, $chipPath)

  $chipPinPen = New-Object System.Drawing.Pen($blueTop, 16)
  $graphics.DrawLine($chipPinPen, 468, 514, 468, 560)
  $graphics.DrawLine($chipPinPen, 764, 514, 764, 560)
  $graphics.DrawLine($chipPinPen, 468, 566, 468, 612)
  $graphics.DrawLine($chipPinPen, 764, 566, 764, 612)

  $pointer = [System.Drawing.PointF[]]@(
    [System.Drawing.PointF]::new(576, 602),
    [System.Drawing.PointF]::new(620, 602),
    [System.Drawing.PointF]::new(598, 636)
  )
  $graphics.FillPolygon($chipBrush, $pointer)

  $fontFamily = New-Object System.Drawing.FontFamily("Segoe UI")
  $aiFont = New-Object System.Drawing.Font($fontFamily, 72, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $textRect = [System.Drawing.RectangleF]::new(500, 476, 230, 110)
  $textFormat = New-Object System.Drawing.StringFormat
  $textFormat.Alignment = [System.Drawing.StringAlignment]::Center
  $textFormat.LineAlignment = [System.Drawing.StringAlignment]::Center
  $graphics.DrawString("AI", $aiFont, $whiteBrush, $textRect, $textFormat)

  $linePen.Width = 22
  $graphics.DrawLine($linePen, 250, 448, 338, 448)
  $graphics.DrawLine($linePen, 206, 524, 294, 524)
  $graphics.DrawLine($linePen, 250, 600, 338, 600)
  $graphics.DrawLine($linePen, 206, 524, 162, 448)
  $graphics.DrawLine($linePen, 162, 448, 162, 600)
  $graphics.DrawLine($linePen, 162, 600, 250, 676)
  $graphics.DrawLine($linePen, 250, 676, 338, 600)
  $graphics.DrawLine($linePen, 338, 600, 294, 524)
  $graphics.DrawLine($linePen, 250, 448, 294, 524)
  $graphics.DrawLine($linePen, 294, 524, 250, 676)

  $linePen.Width = 18
  $graphics.DrawLine($linePen, 336, 612, 408, 720)
  $graphics.DrawLine($linePen, 408, 720, 452, 792)
  $graphics.DrawLine($linePen, 452, 792, 520, 792)
  $graphics.DrawLine($linePen, 486, 760, 486, 824)

  foreach ($node in @(
    @(250, 448), @(338, 448), @(206, 524), @(294, 524), @(162, 448), @(162, 600), @(250, 676), @(338, 600),
    @(408, 720), @(452, 792), @(520, 792), @(486, 760), @(486, 824)
  )) {
    Draw-Node -Graphics $graphics -Brush $nodeBrush -X $node[0] -Y $node[1] -R 16
  }

  $diamondBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 53, 165, 226))
  Fill-Diamond -Graphics $graphics -Brush $diamondBrush -CenterX 540 -CenterY 792 -Radius 12

  $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq "image/png"
  $encoder = [System.Drawing.Imaging.Encoder]::Quality
  $encoderParams = New-Object System.Drawing.Imaging.EncoderParameters(1)
  $encoderParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter($encoder, 100L)
  $bitmap.Save($OutputPath, $codec, $encoderParams)

  $encoderParams.Dispose()
  $diamondBrush.Dispose()
  $chipPinPen.Dispose()
  $chipPath.Dispose()
  $chipBrush.Dispose()
  $textFormat.Dispose()
  $aiFont.Dispose()
  $fontFamily.Dispose()
  $plusVertical.Dispose()
  $plusHorizontal.Dispose()
  $innerVertical.Dispose()
  $innerHorizontal.Dispose()
  $gradientBrush.Dispose()
  $vertical.Dispose()
  $horizontal.Dispose()
  $whiteBrush.Dispose()
  $nodeBrush.Dispose()
  $linePen.Dispose()
  $graphics.Dispose()
  $bitmap.Dispose()
}

Draw-AiIcon -OutputPath (Join-Path $assetsRoot "icon.png") -TransparentBackground:$false
Draw-AiIcon -OutputPath (Join-Path $assetsRoot "adaptive-icon.png") -TransparentBackground:$true

Write-Host "Generated mobile icons in $assetsRoot" -ForegroundColor Green
