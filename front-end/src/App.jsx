import { useState } from "react";
import MapView from "./MapView";
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Container,
  Divider,
  FormControlLabel,
  Grid,
  TextField,
  Typography,
  Alert,
  AlertTitle,
  Paper,
  Chip,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import WaterIcon from "@mui/icons-material/Water";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: "#4fc3f7" },
    background: { default: "#0d1117", paper: "#161b22" },
    text: { primary: "#e6edf3", secondary: "#8b949e" },
    error: { main: "#f85149" },
  },
  typography: {
    fontFamily: '"IBM Plex Mono", "Courier New", monospace',
    h4: {
      fontFamily: '"IBM Plex Sans", sans-serif',
      fontWeight: 600,
      letterSpacing: "-0.5px",
    },
    subtitle2: {
      fontFamily: '"IBM Plex Sans", sans-serif',
      color: "#8b949e",
    },
  },
  shape: { borderRadius: 6 },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid #30363d",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontFamily: '"IBM Plex Mono", monospace',
          fontWeight: 600,
          letterSpacing: "0.5px",
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-root": {
            "& fieldset": { borderColor: "#30363d" },
            "&:hover fieldset": { borderColor: "#8b949e" },
            "&.Mui-focused fieldset": { borderColor: "#4fc3f7" },
          },
          "& .MuiInputLabel-root": { color: "#8b949e" },
          "& .MuiInputLabel-root.Mui-focused": { color: "#4fc3f7" },
          "& .MuiInputBase-input": { fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.82rem" },
        },
      },
    },
  },
});

function StatusChip({ loading, success }) {
  if (loading) return <Chip label="PROCESSING" size="small" color="warning" variant="outlined" sx={{ fontFamily: "inherit", fontSize: "0.7rem" }} />;
  if (success) return <Chip label="COMPLETE" size="small" color="success" variant="outlined" sx={{ fontFamily: "inherit", fontSize: "0.7rem" }} />;
  return <Chip label="READY" size="small" color="default" variant="outlined" sx={{ fontFamily: "inherit", fontSize: "0.7rem", borderColor: "#30363d", color: "#8b949e" }} />;
}

export default function App() {
  const [rainfallData, setRainfallData] = useState("");
  const [alreadyIntensity, setAlreadyIntensity] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectLocation, setProjectLocation] = useState("");
  const [projectDate, setProjectDate] = useState(new Date().toISOString().split("T")[0]);
  const [jobNumber, setJobNumber] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [warnings, setWarnings] = useState(null);
  const [success, setSuccess] = useState(false);

  const hasRainfallData = rainfallData.trim().length > 0;
  const hasCoords = lat.trim().length > 0 && lon.trim().length > 0;
  const canSubmit = !loading && (hasRainfallData || hasCoords);

  const validate = () => {
    if (!hasRainfallData && !hasCoords) {
      return "Provide either rainfall data or both latitude and longitude.";
    }
    if ((lat && !lon) || (!lat && lon)) {
      return "Both latitude and longitude are required when using coordinates.";
    }
    if (lat && isNaN(parseFloat(lat))) return "Latitude must be a valid number.";
    if (lon && isNaN(parseFloat(lon))) return "Longitude must be a valid number.";
    return null;
  };

  const handleSubmit = async () => {
  setError(null);
  setWarnings(null);
  setSuccess(false);

  const validationError = validate();
  if (validationError) { setError(validationError); return; }

  const body = {};
  if (hasRainfallData) body.rainfall_data = rainfallData;
  if (hasRainfallData && alreadyIntensity) body.convert_to_intensity = false;
  if (hasCoords) { body.lat = parseFloat(lat); body.lon = parseFloat(lon); }
  if (projectName) body.project_name = projectName;
  if (projectLocation) body.project_location = projectLocation;
  if (projectDate) body.project_date = projectDate;
  if (jobNumber) body.job_number = jobNumber;

  setLoading(true);
  try {
    // 1. Enqueue the job
    const enqueueRes = await fetch("/generate-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!enqueueRes.ok) {
      const json = await enqueueRes.json().catch(() => ({}));
      throw new Error(json.error || `Server error: ${enqueueRes.status}`);
    }
    const { job_id } = await enqueueRes.json();

    // 2. Poll until done
    await new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const res = await fetch(`/report-status/${job_id}`);

          if (res.status === 202) {
            setTimeout(poll, 3000); // still running, check again in 3s
            return;
          }

          if (!res.ok) {
            const json = await res.json().catch(() => ({}));
            reject(new Error(json.error || `Server error: ${res.status}`));
            return;
          }

          // 3. Success — trigger download
          const warn = res.headers.get("X-Analysis-Warnings");
          if (warn) setWarnings(warn);

          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = "EBD_Analysis_Results.zip";
          a.click();
          URL.revokeObjectURL(url);

          setSuccess(true);
          resolve();
        } catch (err) {
          reject(err);
        }
      };
      poll();
    });

  } catch (err) {
    setError(err.message);
  } finally {
    setLoading(false);
  }
};

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: "100vh", bgcolor: "background.default", py: 5 }}>
        <Container maxWidth="lg">

          {/* Header */}
          <Box sx={{ mb: 4, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
              <WaterIcon sx={{ color: "primary.main", fontSize: 28 }} />
              <Box>
                <Typography variant="h4" sx={{ lineHeight: 1.1 }}>EBD Value Generator </Typography>
                <Typography variant="subtitle2" sx={{ fontSize: "0.8rem" }}>
                  Clean rainfall data copied from reports, convert to intensities, and generate EBD values all in one click.
                </Typography>
              </Box>
            </Box>
            <StatusChip loading={loading} success={success} />
          </Box>

          <Divider sx={{ borderColor: "#21262d", mb: 4 }} />

          {/* Main Grid Container */}
          <Container maxWidth="md">
          <Grid container spacing={3} alignItems="flex-start" justifyContent="center">
            <Grid item xs={12} md={8}>
              {/* Project Inputs */}
              <Paper sx={{ p: 3, mb: 3 }}>
                <Typography variant="overline" sx={{ color: "primary.main", fontSize: "0.68rem", letterSpacing: 2 }}>
                  Project Info
                </Typography>
                <Typography variant="h6" sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 600, mb: 0.5, fontSize: "1rem" }}>
                  Project Details
                </Typography>
                <Typography variant="body2" sx={{ color: "text.secondary", mb: 2.5, fontSize: "0.78rem", lineHeight: 1.6 }}>
                  Optional metadata included in the generated report.
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={6}>
                    <TextField
                      label="Project Name"
                      fullWidth
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      disabled={loading}
                    />
                  </Grid>
                  <Grid item xs={6}>
                    <TextField
                      label="Project Location"
                      fullWidth
                      value={projectLocation}
                      onChange={(e) => setProjectLocation(e.target.value)}
                      disabled={loading}
                    />
                  </Grid>
                  <Grid item xs={6}>
                    <TextField
                      label="Project Number"
                      fullWidth
                      value={jobNumber}
                      onChange={(e) => setJobNumber(e.target.value)}
                      disabled={loading}
                    />
                  </Grid>
                </Grid>
              </Paper>

            {/* Map */}
            <Paper
              sx={{
                p: 3,
                mb: 3,
                height: 700,
                overflow: "hidden",
                border: "1px solid #30363d",
                display: "flex",
                flexDirection: "column"
              }}
            >
              <Typography variant="overline" sx={{ color: "primary.main", fontSize: "0.68rem", letterSpacing: 2 }}>
                Input Method A
              </Typography>
              <Typography variant="h6" sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 600, mb: 0.5, fontSize: "1rem" }}>
                Map Selection
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary", mb: 2, fontSize: "0.78rem", lineHeight: 1.6 }}>
                Click anywhere on the map to select its coordinates. Coordinates will be used to pull data directly from NOAA Atlas-14.
              </Typography>
                <MapView
                  apiKey={import.meta.env.VITE_MAPTILER_API_KEY}
                  lat={lat}
                  lon={lon}
                  onCoordinateSelect={({ lat, lon }) => {
                    setLat(lat);
                    setLon(lon);
                    setSuccess(false);
                  }}
                />
            </Paper>

            {/* Coordinates Input */}
            <Paper sx={{ p: 3, mb: 3 }}>
              <Typography variant="overline" sx={{ color: "primary.main", fontSize: "0.68rem", letterSpacing: 2 }}>
                Input Method B
              </Typography>
              <Typography variant="h6" sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 600, mb: 0.5, fontSize: "1rem" }}>
                Manual Coordinate Entry
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary", mb: 2.5, fontSize: "0.78rem", lineHeight: 1.6 }}>
                Coordinates can be entered in these fields manually, or populated automatically from the map. These are the exact coordinates that will be used to pull data directly from NOAA Atlas-14.
              </Typography>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <TextField
                    label="Latitude"
                    fullWidth
                    value={lat}
                    onChange={(e) => { setLat(e.target.value); setSuccess(false); }}
                    placeholder="47.2349"
                    disabled={loading}
                    inputProps={{ inputMode: "decimal" }}
                  />
                </Grid>
                <Grid item xs={6}>
                  <TextField
                    label="Longitude"
                    fullWidth
                    value={lon}
                    onChange={(e) => { setLon(e.target.value); setSuccess(false); }}
                    placeholder="-111.5879"
                    disabled={loading}
                    inputProps={{ inputMode: "decimal" }}
                  />
                </Grid>
              </Grid>
            </Paper>

              {/* Rainfall Data */}
              <Paper sx={{ p: 3, mb: 3 }}>
                <Typography variant="overline" sx={{ color: "primary.main", fontSize: "0.68rem", letterSpacing: 2 }}>
                  Input Method C
                </Typography>
                <Typography variant="h6" sx={{ fontFamily: '"IBM Plex Sans", sans-serif', fontWeight: 600, mb: 0.5, fontSize: "1rem" }}>
                  Copy/Paste From External Source
                </Typography>
                <Typography variant="body2" sx={{ color: "text.secondary", mb: 2, fontSize: "0.78rem", lineHeight: 1.6 }}>
                  Paste raw rainfall data here. If provided, this will be used instead of fetching from NOAA. Tested to work with the major drainage manuals in Texas.
                </Typography>
                <TextField
                  label="Rainfall Data"
                  multiline
                  rows={14}
                  fullWidth
                  value={rainfallData}
                  onChange={(e) => { setRainfallData(e.target.value); setSuccess(false); }}
                  placeholder={"Paste rainfall data string here…"}
                  disabled={loading}
                  inputProps={{ spellCheck: false }}
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={alreadyIntensity}
                      onChange={(e) => setAlreadyIntensity(e.target.checked)}
                      disabled={loading || !hasRainfallData}
                      size="small"
                      sx={{
                        color: "#30363d",
                        "&.Mui-checked": { color: "primary.main" },
                      }}
                    />
                  }
                  label={
                    <Typography sx={{ fontSize: "0.78rem", color: hasRainfallData ? "text.secondary" : "#30363d", fontFamily: "inherit", userSelect: "none" }}>
                      Data is already in intensity form (skips depth to intensity conversion)
                    </Typography>
                  }
                  sx={{ mt: 1.5, ml: 0.25 }}
                />
              </Paper>

              {/* Submit Button */}
              <Button
                variant="contained"
                fullWidth
                size="large"
                disabled={!canSubmit}
                onClick={handleSubmit}
                startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <DownloadIcon />}
                sx={{
                  py: 1.5,
                  bgcolor: canSubmit ? "primary.main" : undefined,
                  color: "#0d1117",
                  "&:hover": { bgcolor: "#81d4fa" },
                  "&.Mui-disabled": { bgcolor: "#21262d", color: "#8b949e" },
                }}
              >
                {loading ? "Generating Report…" : "Generate & Download Report"}
              </Button>
            </Grid>
          </Grid>
          </Container>

          {/* Status Messages  */}
          <Grid container justifyContent="center">
            <Grid item xs={12} md={8}>
              {error && (
                <Alert severity="error" sx={{ mt: 3, border: "1px solid #f8514933", fontFamily: "inherit" }} onClose={() => setError(null)}>
                  <AlertTitle sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.85rem" }}>Error</AlertTitle>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.8rem" }}>{error}</Typography>
                </Alert>
              )}
              {warnings && (
                <Alert severity="warning" sx={{ mt: 3, fontFamily: "inherit" }} onClose={() => setWarnings(null)}>
                  <AlertTitle sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.85rem" }}>Analysis Warnings</AlertTitle>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.8rem" }}>{warnings}</Typography>
                </Alert>
              )}
              {success && !error && (
                <Alert severity="success" sx={{ mt: 3, border: "1px solid #3fb95033", fontFamily: "inherit" }}>
                  <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.8rem" }}>
                    Report generated successfully. Your download should have started automatically.
                  </Typography>
                </Alert>
              )}
            </Grid>
          </Grid>

        </Container>
      </Box>
    </ThemeProvider>
  );
}