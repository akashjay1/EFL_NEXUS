using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using EflNexus.Core.Infrastructure;
using OpenCvSharp;
using OpenCvSharp.Extensions;
using ZXing;
using ZXing.Common;
using ZXing.Windows.Compatibility;

namespace EflNexus.Core.GrnOcr;

/// <summary>
/// Local gate-pass recognition (1:1 parity with grn_ocr.py).
/// Only a number spatially adjacent to a GATE PASS header qualifies.
/// </summary>
public static partial class GrnOcrEngine
{
    public const string RecognitionVersion = "grn-header-v2";

    [GeneratedRegex(@"[^A-Z]")]
    private static partial Regex NonAlphaUpperRegex();

    [GeneratedRegex(@"^[0-9]+$")]
    private static partial Regex DigitsOnlyRegex();

    [GeneratedRegex(@"[:\s]")]
    private static partial Regex ColonOrSpaceRegex();

    public static string RuntimeDirectory()
        => AppPaths.ResolveResourcePath(Path.Combine("assets", "grn_ocr"));

    public static List<OcrWord> ReadWords(
        Mat image,
        int psm = 11,
        Stopwatch? stopwatch = null,
        double? timeoutSeconds = null)
    {
        var runtime = RuntimeDirectory();
        var executable = Path.Combine(runtime, "tesseract.exe");
        var trainedData = Path.Combine(runtime, "tessdata", "eng.traineddata");
        if (!File.Exists(executable) || !File.Exists(trainedData))
            throw new InvalidOperationException("OCR runtime is missing. Reinstall the complete NEXUS package.");

        double? remainingSeconds = null;
        if (stopwatch is not null && timeoutSeconds.HasValue)
        {
            remainingSeconds = timeoutSeconds.Value - stopwatch.Elapsed.TotalSeconds;
            if (remainingSeconds <= 0)
                throw new TimeoutException("Local OCR reached its document time limit.");
        }

        var folder = Path.Combine(Path.GetTempPath(), $"nexus-grn-{Guid.NewGuid():N}");
        Directory.CreateDirectory(folder);
        string tsvOutput;
        try
        {
            var sourcePath = Path.Combine(folder, "input.png");
            Cv2.ImEncode(".png", image, out var pngBytes);
            File.WriteAllBytes(sourcePath, pngBytes);

            var psi = new ProcessStartInfo
            {
                FileName = executable,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                CreateNoWindow = true
            };
            psi.ArgumentList.Add(sourcePath);
            psi.ArgumentList.Add("stdout");
            psi.ArgumentList.Add("--tessdata-dir");
            psi.ArgumentList.Add(Path.Combine(runtime, "tessdata"));
            psi.ArgumentList.Add("-l");
            psi.ArgumentList.Add("eng");
            psi.ArgumentList.Add("--psm");
            psi.ArgumentList.Add(psm.ToString(CultureInfo.InvariantCulture));
            psi.ArgumentList.Add("tsv");

            using var process = Process.Start(psi)
                ?? throw new InvalidOperationException("Failed to start tesseract.exe.");

            var stdoutTask = process.StandardOutput.ReadToEndAsync();
            var stderrTask = process.StandardError.ReadToEndAsync();

            int waitMs = remainingSeconds.HasValue
                ? Math.Max(10, (int)(Math.Min(35.0, remainingSeconds.Value) * 1000.0))
                : 35_000;

            if (!process.WaitForExit(waitMs))
            {
                try { process.Kill(entireProcessTree: true); } catch { }
                throw new TimeoutException("Local OCR reached its document time limit.");
            }

            Task.WaitAll(stdoutTask, stderrTask);
            if (process.ExitCode != 0)
            {
                var err = stderrTask.Result;
                throw new InvalidOperationException("Tesseract could not read the photo: " + (err.Length > 300 ? err[..300] : err));
            }
            tsvOutput = stdoutTask.Result;
        }
        finally
        {
            try { Directory.Delete(folder, recursive: true); } catch { }
        }

        return ParseTesseractTsv(tsvOutput);
    }

    internal static List<OcrWord> ParseTesseractTsv(string tsvOutput)
    {
        var words = new List<OcrWord>();
        using var reader = new StringReader(tsvOutput);
        var headerLine = reader.ReadLine();
        if (string.IsNullOrEmpty(headerLine))
            return words;

        var headers = headerLine.Split('\t');
        int IndexOfCol(string name) => Array.FindIndex(headers, h => string.Equals(h.Trim(), name, StringComparison.OrdinalIgnoreCase));

        int iLevel = IndexOfCol("level");
        int iPage = IndexOfCol("page_num");
        int iBlock = IndexOfCol("block_num");
        int iPar = IndexOfCol("par_num");
        int iLine = IndexOfCol("line_num");
        int iLeft = IndexOfCol("left");
        int iTop = IndexOfCol("top");
        int iWidth = IndexOfCol("width");
        int iHeight = IndexOfCol("height");
        int iConf = IndexOfCol("conf");
        int iText = IndexOfCol("text");
        if (iLevel < 0 || iLeft < 0 || iTop < 0 || iWidth < 0 || iHeight < 0 || iConf < 0 || iText < 0)
            return words;

        string? rowLine;
        while ((rowLine = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrEmpty(rowLine))
                continue;
            var cols = rowLine.Split('\t');
            if (cols.Length <= iText)
                continue;
            if (!string.Equals(cols[iLevel], "5", StringComparison.Ordinal))
                continue;

            var text = cols[iText].Trim();
            if (string.IsNullOrEmpty(text))
                continue;

            if (!double.TryParse(cols[iConf], NumberStyles.Float, CultureInfo.InvariantCulture, out var conf))
                continue;
            if (!double.TryParse(cols[iLeft], NumberStyles.Float, CultureInfo.InvariantCulture, out var left))
                continue;
            if (!double.TryParse(cols[iTop], NumberStyles.Float, CultureInfo.InvariantCulture, out var top))
                continue;
            if (!double.TryParse(cols[iWidth], NumberStyles.Float, CultureInfo.InvariantCulture, out var w))
                continue;
            if (!double.TryParse(cols[iHeight], NumberStyles.Float, CultureInfo.InvariantCulture, out var h))
                continue;

            words.Add(new OcrWord
            {
                Text = text,
                Confidence = conf,
                Left = left,
                Top = top,
                Width = w,
                Height = h,
                Line =
                [
                    iPage >= 0 && iPage < cols.Length ? cols[iPage] : "",
                    iBlock >= 0 && iBlock < cols.Length ? cols[iBlock] : "",
                    iPar >= 0 && iPar < cols.Length ? cols[iPar] : "",
                    iLine >= 0 && iLine < cols.Length ? cols[iLine] : ""
                ]
            });
        }
        return words;
    }

    private static string CleanAlpha(string text)
        => NonAlphaUpperRegex().Replace((text ?? "").ToUpperInvariant(), "");

    public static List<(double Left, double Top, double Right, double Bottom)> HeaderAnchors(
        IReadOnlyList<OcrWord> words,
        double width,
        double height)
    {
        var anchors = new List<(double Left, double Top, double Right, double Bottom)>();
        foreach (var gate in words)
        {
            if (gate.Top > height * 0.5)
                continue;
            var cg = CleanAlpha(gate.Text);
            if (cg == "GATEPASS")
                anchors.Add((gate.Left, gate.Top, gate.Left + gate.Width, gate.Top + gate.Height));
            if (cg != "GATE")
                continue;

            foreach (var word in words)
            {
                double gap = word.Left - gate.Left - gate.Width;
                if (CleanAlpha(word.Text) == "PASS"
                    && gap >= 0
                    && gap < Math.Max(width * 0.035, gate.Height * 2.0)
                    && Math.Abs(word.Top - gate.Top) <= Math.Max(word.Height, gate.Height) * 0.7)
                {
                    anchors.Add((
                        gate.Left,
                        Math.Min(gate.Top, word.Top),
                        word.Left + word.Width,
                        Math.Max(gate.Top + gate.Height, word.Top + word.Height)));
                }
            }
        }
        return anchors;
    }

    public static double SkewAngle(Mat image)
    {
        using var gray = image.Channels() == 1 ? image.Clone() : image.CvtColor(ColorConversionCodes.BGR2GRAY);
        using var edges = new Mat();
        Cv2.Canny(gray, edges, 60, 160);
        var lines = Cv2.HoughLinesP(edges, 1, Math.PI / 1800.0, 80, minLineLength: Math.Max(90, image.Width / 4), maxLineGap: 30);
        if (lines is null || lines.Length == 0)
            return 0.0;

        var angles = new List<double>();
        foreach (var seg in lines)
        {
            double angle = Math.Atan2(seg.P2.Y - seg.P1.Y, seg.P2.X - seg.P1.X) * (180.0 / Math.PI);
            if (Math.Abs(angle) < 18.0)
                angles.Add(angle);
        }
        if (angles.Count == 0)
            return 0.0;

        angles.Sort();
        int mid = angles.Count / 2;
        return angles.Count % 2 == 1 ? angles[mid] : (angles[mid - 1] + angles[mid]) / 2.0;
    }

    /// <summary>
    /// Rotates counter-clockwise by positive <paramref name="angle"/> degrees with white expansion fill,
    /// matching Pillow's <c>Image.rotate(angle, BICUBIC, expand=True, fillcolor="white")</c>.
    /// </summary>
    public static Mat RotateWithWhiteFill(Mat source, double angle)
    {
        int normalizedInt = (int)Math.Round(angle);
        if (Math.Abs(angle - normalizedInt) < 1e-6)
        {
            int mod = ((normalizedInt % 360) + 360) % 360;
            if (mod == 0)
                return source.Clone();
            if (mod == 90)
            {
                var dst = new Mat();
                Cv2.Rotate(source, dst, RotateFlags.Rotate90Counterclockwise);
                return dst;
            }
            if (mod == 180)
            {
                var dst = new Mat();
                Cv2.Rotate(source, dst, RotateFlags.Rotate180);
                return dst;
            }
            if (mod == 270)
            {
                var dst = new Mat();
                Cv2.Rotate(source, dst, RotateFlags.Rotate90Clockwise);
                return dst;
            }
        }

        var center = new Point2f(source.Width / 2.0f, source.Height / 2.0f);
        using var matrix = Cv2.GetRotationMatrix2D(center, angle, 1.0);
        double cos = Math.Abs(matrix.At<double>(0, 0));
        double sin = Math.Abs(matrix.At<double>(0, 1));
        int newWidth = (int)Math.Ceiling(source.Height * sin + source.Width * cos);
        int newHeight = (int)Math.Ceiling(source.Height * cos + source.Width * sin);
        matrix.Set(0, 2, matrix.At<double>(0, 2) + (newWidth / 2.0 - center.X));
        matrix.Set(1, 2, matrix.At<double>(1, 2) + (newHeight / 2.0 - center.Y));

        var rotated = new Mat();
        Cv2.WarpAffine(
            source,
            rotated,
            matrix,
            new OpenCvSharp.Size(newWidth, newHeight),
            InterpolationFlags.Cubic,
            BorderTypes.Constant,
            new Scalar(255, 255, 255));
        return rotated;
    }

    public static List<OcrWord> HeaderNumberEvidence(
        IReadOnlyList<OcrWord> words,
        double width,
        double height)
    {
        var evidence = new List<OcrWord>();
        foreach (var (left, top, right, bottom) in HeaderAnchors(words, width, height))
        {
            double h = bottom - top;
            double maxRight = Math.Min(width, right + Math.Min(width / 3.0, h * 12.0));
            double anchorCenterY = (top + bottom) / 2.0;

            var inline = words
                .Where(w => w.Left >= right && w.Left < maxRight
                    && Math.Abs(w.Top + w.Height / 2.0 - anchorCenterY) < h * 0.8)
                .OrderBy(w => w.Left)
                .ToList();

            if (inline.Count > 0 && CleanAlpha(inline[0].Text) is "NUMBER" or "NO" or "ID")
                continue;

            OcrWord? previous = null;
            foreach (var word in inline)
            {
                if (previous is null && word.Left - right > Math.Max(h * 6.0, width * 0.06))
                    break;
                if (previous is not null && word.Left - previous.Left - previous.Width > h * 2.0)
                    break;
                if (DigitsOnlyRegex().IsMatch(word.Text))
                {
                    evidence.Add(new OcrWord
                    {
                        Text = word.Text,
                        Confidence = word.Confidence,
                        Left = word.Left,
                        Top = word.Top,
                        Width = word.Width,
                        Height = word.Height,
                        Line = word.Line,
                        Anchor = [left, top, right, bottom]
                    });
                    previous = word;
                }
                else if (!string.IsNullOrEmpty(ColonOrSpaceRegex().Replace(word.Text, "")))
                {
                    break;
                }
            }
        }
        return evidence;
    }

    internal static Mat AutoContrastGray(Mat gray, double cutoffPercent = 1.0)
    {
        int[] hist = new int[256];
        using var histMat = new Mat();
        Cv2.CalcHist([gray], [0], null, histMat, 1, [256], [new Rangef(0, 256)]);
        for (int i = 0; i < 256; i++)
            hist[i] = (int)Math.Round(histMat.At<float>(i));

        int total = gray.Rows * gray.Cols;
        int cut = (int)(total * cutoffPercent / 100.0);

        int lo = 0;
        int acc = 0;
        for (int i = 0; i < 256; i++)
        {
            acc += hist[i];
            if (acc > cut)
            {
                lo = i;
                break;
            }
        }

        int hi = 255;
        acc = 0;
        for (int i = 255; i >= 0; i--)
        {
            acc += hist[i];
            if (acc > cut)
            {
                hi = i;
                break;
            }
        }

        if (hi <= lo)
            return gray.Clone();

        byte[] lutData = new byte[256];
        double scale = 255.0 / (hi - lo);
        for (int i = 0; i < 256; i++)
        {
            int v = (int)Math.Round((i - lo) * scale);
            lutData[i] = (byte)Math.Clamp(v, 0, 255);
        }

        using var lut = Mat.FromPixelData(1, 256, MatType.CV_8UC1, lutData);
        var dst = new Mat();
        Cv2.LUT(gray, lut, dst);
        return dst;
    }

    internal static List<(string Name, Mat Image)> BuildImageVariants(Mat image)
    {
        var list = new List<(string Name, Mat Image)>();
        var gray = image.Channels() == 1 ? image.Clone() : image.CvtColor(ColorConversionCodes.BGR2GRAY);
        list.Add(("grayscale", gray));
        list.Add(("contrast", AutoContrastGray(gray, 1.0)));

        int minDim = Math.Min(gray.Rows, gray.Cols);
        if (minDim >= 3)
        {
            int block = Math.Max(3, Math.Min(41, (minDim / 2) * 2 - 1));
            var adaptive = new Mat();
            Cv2.AdaptiveThreshold(gray, adaptive, 255, AdaptiveThresholdTypes.GaussianC, ThresholdTypes.Binary, block, 13);
            list.Add(("adaptive", adaptive));
        }
        return list;
    }

    private static Mat ThumbnailMax(Mat source, int maxSide)
    {
        if (source.Width <= maxSide && source.Height <= maxSide)
            return source.Clone();
        double ratio = Math.Min((double)maxSide / source.Width, (double)maxSide / source.Height);
        int w = Math.Max(1, (int)Math.Round(source.Width * ratio));
        int h = Math.Max(1, (int)Math.Round(source.Height * ratio));
        var dst = new Mat();
        Cv2.Resize(source, dst, new OpenCvSharp.Size(w, h), 0, 0, InterpolationFlags.Lanczos4);
        return dst;
    }

    private static Mat CropBounds(Mat source, int left, int top, int right, int bottom)
    {
        int x1 = Math.Clamp(left, 0, Math.Max(0, source.Width - 1));
        int y1 = Math.Clamp(top, 0, Math.Max(0, source.Height - 1));
        int x2 = Math.Clamp(right, x1 + 1, source.Width);
        int y2 = Math.Clamp(bottom, y1 + 1, source.Height);
        return new Mat(source, new Rect(x1, y1, x2 - x1, y2 - y1)).Clone();
    }

    public static OcrExtractionResult ExtractGatepass(string imagePath, string outputDirectory, double timeoutSeconds = 10.0)
    {
        var sw = Stopwatch.StartNew();
        Directory.CreateDirectory(outputDirectory);

        var fileBytes = File.ReadAllBytes(imagePath);
        using var original = Cv2.ImDecode(fileBytes, ImreadModes.Color);
        if (original.Empty())
            throw new InvalidOperationException("Corrupt or unreadable image file.");

        var warnings = new List<string>();
        var candidates = new SortedSet<string>(StringComparer.Ordinal);
        var barcodeValues = new SortedSet<string>(StringComparer.Ordinal);
        var evidence = new List<OcrEvidence>();
        string workingPath = "";
        string headerPath = "";
        int? selectedRotation = null;
        List<int>? headerBox = null;

        try
        {
            int[] orientations = original.Height >= original.Width ? [0, 180, 90, 270] : [90, 270, 0, 180];
            var passes = new List<(int Rotation, bool Thresholded)>();
            foreach (bool thr in new[] { false, true })
                foreach (int r in orientations)
                    passes.Add((r, thr));

            var barcodeReader = new BarcodeReader
            {
                AutoRotate = false,
                Options = new DecodingOptions
                {
                    TryHarder = true,
                    PossibleFormats = [BarcodeFormat.All_1D]
                }
            };

            foreach (var (rotation, thresholded) in passes)
            {
                if (sw.Elapsed.TotalSeconds >= timeoutSeconds)
                    throw new TimeoutException();

                using var rotated = RotateWithWhiteFill(original, rotation);
                using var previewInitial = ThumbnailMax(rotated, 2200);
                double angle = SkewAngle(previewInitial);

                using var working = Math.Abs(angle) > 0.3 ? RotateWithWhiteFill(rotated, angle) : rotated.Clone();
                using var previewThumb = ThumbnailMax(working, 2200);

                Mat preview;
                if (Math.Max(previewThumb.Width, previewThumb.Height) < 1800)
                {
                    double factor = Math.Min(2.0, 1800.0 / Math.Max(previewThumb.Width, previewThumb.Height));
                    preview = new Mat();
                    Cv2.Resize(previewThumb, preview,
                        new OpenCvSharp.Size((int)Math.Round(previewThumb.Width * factor), (int)Math.Round(previewThumb.Height * factor)),
                        0, 0, InterpolationFlags.Lanczos4);
                }
                else
                {
                    preview = previewThumb.Clone();
                }

                using (preview)
                {
                    using var topHalf = new Mat(preview, new Rect(0, 0, preview.Width, Math.Max(1, preview.Height / 2))).Clone();
                    Mat search = topHalf;
                    List<(string Name, Mat Image)>? topVariants = null;
                    if (thresholded)
                    {
                        topVariants = BuildImageVariants(topHalf);
                        search = topVariants[^1].Image;
                    }

                    List<OcrWord> words;
                    try
                    {
                        words = ReadWords(search, 11, sw, timeoutSeconds);
                    }
                    finally
                    {
                        if (topVariants is not null)
                        {
                            foreach (var (_, mat) in topVariants)
                                mat.Dispose();
                        }
                    }

                    var anchors = HeaderAnchors(words, preview.Width, preview.Height);
                    if (anchors.Count == 0)
                        continue;

                    selectedRotation = rotation;
                    workingPath = Path.Combine(outputDirectory, "oriented.png");
                    Cv2.ImEncode(".png", working, out var workingBytes);
                    File.WriteAllBytes(workingPath, workingBytes);

                    double sx = (double)working.Width / preview.Width;
                    double sy = (double)working.Height / preview.Height;

                    (int X1, int Y1, int X2, int Y2) ToNative(double x1, double y1, double x2, double y2) => (
                        Math.Max(0, (int)Math.Round(x1 * sx)),
                        Math.Max(0, (int)Math.Round(y1 * sy)),
                        Math.Min(working.Width, (int)Math.Round(x2 * sx)),
                        Math.Min(working.Height, (int)Math.Round(y2 * sy)));

                    foreach (var anchor in anchors)
                    {
                        var (left, top, right, bottom) = anchor;
                        double h = bottom - top;
                        var inline = words
                            .Where(w => w.Left >= right && w.Left < right + preview.Width / 3.0
                                && Math.Abs(w.Top + w.Height / 2.0 - (top + bottom) / 2.0) < h * 0.8)
                            .OrderBy(w => w.Left)
                            .ToList();

                        if (inline.Count > 0 && CleanAlpha(inline[0].Text) is "NUMBER" or "NO" or "ID")
                            continue;

                        double numX1 = right;
                        double numY1 = Math.Max(0, top - Math.Floor(h / 2.0));
                        double numX2 = Math.Min(preview.Width, right + Math.Min(preview.Width / 3.0, h * 12.0));
                        double numY2 = Math.Min(preview.Height, bottom + Math.Floor(h / 2.0));

                        double barcodeRight = Math.Min(preview.Width, right + preview.Width / 3.0);
                        var nh = ToNative(
                            Math.Max(0, left - h),
                            Math.Max(0, top - h),
                            Math.Min(preview.Width, barcodeRight + h),
                            Math.Min(preview.Height, bottom + h * 7.0));

                        using var header = CropBounds(working, nh.X1, nh.Y1, nh.X2, nh.Y2);
                        if (string.IsNullOrEmpty(headerPath))
                        {
                            headerPath = Path.Combine(outputDirectory, "header.png");
                            Cv2.ImEncode(".png", header, out var hdrBytes);
                            File.WriteAllBytes(headerPath, hdrBytes);
                            headerBox = [nh.X1, nh.Y1, nh.X2, nh.Y2];
                        }

                        foreach (int scale in new[] { 1, 2, 3 })
                        {
                            if (sw.Elapsed.TotalSeconds >= timeoutSeconds)
                                throw new TimeoutException();

                            using var enlarged = scale == 1
                                ? header.Clone()
                                : header.Resize(new OpenCvSharp.Size(header.Width * scale, header.Height * scale), 0, 0, InterpolationFlags.Cubic);

                            using var bmp = BitmapConverter.ToBitmap(enlarged);
                            var decoded = barcodeReader.DecodeMultiple(bmp);
                            if (decoded is not null)
                            {
                                foreach (var barcode in decoded)
                                {
                                    if (string.IsNullOrEmpty(barcode.Text) || !DigitsOnlyRegex().IsMatch(barcode.Text))
                                        continue;
                                    var pts = barcode.ResultPoints;
                                    if (pts is null || pts.Length == 0)
                                        continue;

                                    double cx = (pts.Average(p => p.X) / scale + nh.X1) / sx;
                                    double cy = (pts.Average(p => p.Y) / scale + nh.Y1) / sy;
                                    if (cx >= right - h && cx <= barcodeRight && cy >= bottom && cy <= bottom + h * 7.0)
                                        barcodeValues.Add(barcode.Text);
                                }
                            }
                            if (barcodeValues.Count > 0)
                                break;
                        }

                        var eligible = HeaderNumberEvidence(words, preview.Width, preview.Height)
                            .Where(w => w.Anchor is not null
                                && Math.Abs(w.Anchor[0] - left) < 1e-6
                                && Math.Abs(w.Anchor[1] - top) < 1e-6
                                && Math.Abs(w.Anchor[2] - right) < 1e-6
                                && Math.Abs(w.Anchor[3] - bottom) < 1e-6)
                            .ToList();

                        foreach (var word in eligible)
                        {
                            candidates.Add(word.Text);
                            var nb = ToNative(word.Left, word.Top, word.Left + word.Width, word.Top + word.Height);
                            evidence.Add(new OcrEvidence
                            {
                                Source = "local",
                                Value = word.Text,
                                Confidence = word.Confidence,
                                Box = [nb.X1, nb.Y1, nb.X2, nb.Y2]
                            });
                        }

                        if (eligible.Any(w => (w.Confidence ?? 0) < 60))
                            warnings.Add("Low-confidence printed number; compare every digit with the photo.");

                        var digitImages = new List<Mat>();
                        try
                        {
                            foreach (var word in eligible)
                            {
                                double pad = Math.Max(4.0, Math.Floor(word.Height / 3.0));
                                var nw = ToNative(word.Left - pad, word.Top - pad, word.Left + word.Width + pad, word.Top + word.Height + pad);
                                digitImages.Add(CropBounds(working, nw.X1, nw.Y1, nw.X2, nw.Y2));
                            }
                            var nNum = ToNative(numX1, numY1, numX2, numY2);
                            digitImages.Add(CropBounds(working, nNum.X1, nNum.Y1, nNum.X2, nNum.Y2));

                            foreach (var rawDigit in digitImages)
                            {
                                Mat digitImg = rawDigit;
                                Mat? upscaled = null;
                                if (digitImg.Height < 80)
                                {
                                    double factor = Math.Min(3.0, Math.Max(1.0, 80.0 / Math.Max(1, digitImg.Height)));
                                    upscaled = digitImg.Resize(
                                        new OpenCvSharp.Size(Math.Max(1, (int)Math.Round(digitImg.Width * factor)),
                                                 Math.Max(1, (int)Math.Round(digitImg.Height * factor))),
                                        0, 0, InterpolationFlags.Lanczos4);
                                    digitImg = upscaled;
                                }

                                try
                                {
                                    var variants = new List<(string Name, Mat Image)> { ("original", digitImg.Clone()) };
                                    variants.AddRange(BuildImageVariants(digitImg));

                                    try
                                    {
                                        foreach (var (variantName, variantMat) in variants)
                                        {
                                            var reread = ReadWords(variantMat, 7, sw, timeoutSeconds);
                                            var joined = string.Join(" ", reread.Select(w => w.Text)).Trim().Trim(':', ' ');
                                            if (DigitsOnlyRegex().IsMatch(joined))
                                            {
                                                candidates.Add(joined);
                                                double minConf = reread.Count > 0 ? reread.Min(w => w.Confidence ?? 0) : 0;
                                                evidence.Add(new OcrEvidence
                                                {
                                                    Source = "local",
                                                    Value = joined,
                                                    Confidence = minConf,
                                                    Variant = variantName
                                                });
                                                if (minConf < 60)
                                                    warnings.Add("Low-confidence printed number; compare every digit with the photo.");
                                            }

                                            if (!string.IsNullOrEmpty(joined)
                                                && barcodeValues.Count == 1 && barcodeValues.Contains(joined)
                                                && candidates.Count == 1 && candidates.Contains(joined))
                                                break;

                                            if (variantName == "original"
                                                && !string.IsNullOrEmpty(joined)
                                                && candidates.Count == 1 && candidates.Contains(joined)
                                                && reread.All(w => (w.Confidence ?? 0) >= 60))
                                                break;
                                        }
                                    }
                                    finally
                                    {
                                        foreach (var (_, mat) in variants)
                                            mat.Dispose();
                                    }
                                }
                                finally
                                {
                                    upscaled?.Dispose();
                                }
                            }
                        }
                        finally
                        {
                            foreach (var di in digitImages)
                                di.Dispose();
                        }
                    }
                    break;
                }
            }
        }
        catch (TimeoutException)
        {
            warnings.Add($"Local OCR reached its {timeoutSeconds:G}-second document time limit; review or use cloud OCR.");
        }

        var allValues = new SortedSet<string>(candidates, StringComparer.Ordinal);
        allValues.UnionWith(barcodeValues);

        var gatepass = allValues.Count == 1 ? allValues.First() : "";
        if (allValues.Count > 1)
            warnings.Add("Conflicting or multiple readings. Enter the number from the photo manually.");
        else if (string.IsNullOrEmpty(gatepass))
            warnings.Add("No unambiguous gate pass beside the header. Enter it manually or retry with a clearer photo.");
        else if (barcodeValues.Count == 0)
            warnings.Add("Header barcode could not be read; verify the printed number.");
        else if (candidates.Count == 0)
            warnings.Add("Only the header barcode was readable; verify the printed number.");

        var sources = new List<string>();
        if (candidates.Count > 0) sources.Add("local");
        if (barcodeValues.Count > 0) sources.Add("barcode");

        return new OcrExtractionResult
        {
            Gatepass = gatepass,
            OcrCandidates = [.. candidates],
            BarcodeCandidates = [.. barcodeValues],
            Warnings = warnings.Distinct(StringComparer.Ordinal).ToList(),
            HeaderPath = headerPath,
            WorkingPath = workingPath,
            RecognitionSource = sources.Count > 0 ? string.Join(" + ", sources) : "local",
            RecognitionVersion = RecognitionVersion,
            ProcessingStatus = "local_complete",
            Evidence = evidence,
            HeaderBox = headerBox,
            Rotation = selectedRotation,
            Seconds = Math.Round(sw.Elapsed.TotalSeconds, 3)
        };
    }
}
