import gradio as gr
import json
import torch
import wavio
from tqdm import tqdm
from huggingface_hub import snapshot_download
from models import AudioDiffusion, DDPMScheduler
from audioldm.audio.stft import TacotronSTFT
from audioldm.variational_autoencoder import AutoencoderKL
from gradio import Markdown

class Tango:
    def __init__(self, name="declare-lab/tango", device="cuda:0"):
        
        path = snapshot_download(repo_id=name)
        
        vae_config = json.load(open("{}/vae_config.json".format(path)))
        stft_config = json.load(open("{}/stft_config.json".format(path)))
        main_config = json.load(open("{}/main_config.json".format(path)))
        
        self.vae = AutoencoderKL(**vae_config).to(device)
        self.stft = TacotronSTFT(**stft_config).to(device)
        self.model = AudioDiffusion(**main_config).to(device)
        
        vae_weights = torch.load("{}/pytorch_model_vae.bin".format(path), map_location=device)
        stft_weights = torch.load("{}/pytorch_model_stft.bin".format(path), map_location=device)
        main_weights = torch.load("{}/pytorch_model_main.bin".format(path), map_location=device)
        
        self.vae.load_state_dict(vae_weights)
        self.stft.load_state_dict(stft_weights)
        self.model.load_state_dict(main_weights)

        print ("Successfully loaded checkpoint from:", name)
        
        self.vae.eval()
        self.stft.eval()
        self.model.eval()
        
        self.scheduler = DDPMScheduler.from_pretrained(main_config["scheduler_name"], subfolder="scheduler")
        
    def chunks(self, lst, n):
        """ Yield successive n-sized chunks from a list. """
        for i in range(0, len(lst), n):
            yield lst[i:i + n]
        
    def generate(self, prompt, steps=100, guidance=3, samples=1, disable_progress=True):
        """ Genrate audio for a single prompt string. """
        with torch.no_grad():
            latents = self.model.inference([prompt], self.scheduler, steps, guidance, samples, disable_progress=disable_progress)
            mel = self.vae.decode_first_stage(latents)
            wave = self.vae.decode_to_waveform(mel)
        return wave[0]
    
    def generate_for_batch(self, prompts, steps=200, guidance=3, samples=1, batch_size=8, disable_progress=True):
        """ Genrate audio for a list of prompt strings. """
        outputs = []
        for k in tqdm(range(0, len(prompts), batch_size)):
            batch = prompts[k: k+batch_size]
            with torch.no_grad():
                latents = self.model.inference(batch, self.scheduler, steps, guidance, samples, disable_progress=disable_progress)
                mel = self.vae.decode_first_stage(latents)
                wave = self.vae.decode_to_waveform(mel)
                outputs += [item for item in wave]
        if samples == 1:
            return outputs
        else:
            return list(self.chunks(outputs, samples))

# Initialize Tango model
tango = Tango()

def gradio_generate(prompt):
    
    output_wave = tango.generate(prompt)
    
    # Save the output_wave as a temporary WAV file
    output_filename = "temp_output.wav"
    wavio.write(output_filename, output_wave, rate=22050, sampwidth=2)
    
    return output_filename

# Add the description text box
description_text = '''
TANGO is a latent diffusion model (LDM) for text-to-audio (TTA) generation. TANGO can generate realistic audios including human sounds, animal sounds, natural and artificial sounds and sound effects from textual prompts. We use the frozen instruction-tuned LLM Flan-T5 as the text encoder and train a UNet based diffusion model for audio generation. We perform comparably to current state-of-the-art models for TTA across both objective and subjective metrics, despite training the LDM on a 63 times smaller dataset. We release our model, training, inference code, and pre-trained checkpoints for the research community.
'''

# Define Gradio input and output components
input_text = gr.inputs.Textbox(lines=2, label="Prompt")
output_audio = gr.outputs.Audio(label="Generated Audio", type="filepath")

# Create Gradio interface
gr_interface = gr.Interface(
    fn=gradio_generate,
    inputs=input_text,
    outputs=[output_audio],
    title="Tango Audio Generator",
    description="Generate audio using Tango model by providing a text prompt.",
    allow_flagging=False,
        examples=[
        ["A Dog Barking"],
        ["A loud thunderstorm"],
    ],
)

# Launch Gradio app
gr_interface.launch()
